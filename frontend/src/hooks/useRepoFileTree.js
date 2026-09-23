import { useCallback, useEffect, useRef, useState } from 'react'
import { UnauthorizedError, openIndexedFilesStream } from '../api/client'
import { parseEventStream } from '../api/sse'
import { buildFileTree } from '../utils/buildFileTree'

const STREAM_RECONNECT_DELAY_MS = 1500
const RESTING_REPO_STATUSES = new Set(['completed', 'failed', 'paused'])
const TERMINAL_FILE_STATUSES = new Set(['indexed', 'skipped', 'failed'])

function upsertByFilePath(files, incomingFile) {
  const index = files.findIndex((file) => file.file_path === incomingFile.file_path)
  if (index === -1) {
    return [...files, incomingFile]
  }
  const next = [...files]
  next[index] = incomingFile
  return next
}

export function useRepoFileTree(token, repoId, onUnauthorized) {
  const [trackedRepoId, setTrackedRepoId] = useState(repoId)
  const [files, setFiles] = useState([])
  const [repoStatus, setRepoStatus] = useState(null)
  const [status, setStatus] = useState(repoId ? 'loading' : 'idle')
  const [retryNonce, setRetryNonce] = useState(0)

  if (trackedRepoId !== repoId) {
    setTrackedRepoId(repoId)
    setFiles([])
    setRepoStatus(null)
    setStatus(repoId ? 'loading' : 'idle')
  }

  const repoStatusRef = useRef(repoStatus)
  useEffect(() => {
    repoStatusRef.current = repoStatus
  }, [repoStatus])

  useEffect(() => {
    if (!repoId) {
      return
    }
    const controller = new AbortController()

    async function run() {
      // Only a fully-failed *connection attempt* stops the loop for good -- a drop
      // partway through an already-open stream is treated as transient and retried,
      // since the next reconnect still has to pass this same "did it even open" gate.
      while (!controller.signal.aborted) {
        let opened = false
        try {
          const response = await openIndexedFilesStream(token, repoId, controller.signal)
          opened = true
          setStatus('ready')
          for await (const event of parseEventStream(response)) {
            if (event.type === 'status') {
              setRepoStatus(JSON.parse(event.data))
              continue
            }
            const file = JSON.parse(event.data)
            setFiles((previous) => upsertByFilePath(previous, file))
          }
        } catch (error) {
          if (controller.signal.aborted) {
            return
          }
          if (error instanceof UnauthorizedError) {
            onUnauthorized()
            return
          }
          if (!opened) {
            setStatus('error')
            return
          }
        }
        if (controller.signal.aborted || RESTING_REPO_STATUSES.has(repoStatusRef.current?.status)) {
          return
        }
        await new Promise((resolve) => setTimeout(resolve, STREAM_RECONNECT_DELAY_MS))
      }
    }

    run()
    return () => controller.abort()
  }, [token, repoId, onUnauthorized, retryNonce])

  const refresh = useCallback(() => setRetryNonce((nonce) => nonce + 1), [])
  const settledFileCount = files.filter((file) => TERMINAL_FILE_STATUSES.has(file.status)).length
  const failedFileCount = files.filter((file) => file.status === 'failed').length
  const nodes = buildFileTree(
    files.map((file) => ({
      path: file.file_path,
      status: file.status,
      statusReason: file.status_reason,
      indexedAt: file.indexed_at,
    }))
  )
  return { nodes, status, repoStatus, totalFileCount: files.length, settledFileCount, failedFileCount, refresh }
}

export { RESTING_REPO_STATUSES }
