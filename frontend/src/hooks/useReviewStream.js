import { useEffect, useRef, useState } from 'react'
import { UnauthorizedError, openReviewStream } from '../api/client'
import { parseEventStream } from '../api/sse'

const STREAM_RECONNECT_DELAY_MS = 1500
const TERMINAL_STATUSES = new Set(['completed', 'failed'])

export function useReviewStream(token, reviewId, onUnauthorized) {
  const [job, setJob] = useState(null)
  const [reviewedFiles, setReviewedFiles] = useState(new Set())
  const [failedFiles, setFailedFiles] = useState(new Set())
  const [agentProgress, setAgentProgress] = useState({})
  const [connectionStatus, setConnectionStatus] = useState('loading')

  const jobStatusRef = useRef(null)
  useEffect(() => {
    jobStatusRef.current = job?.status
  }, [job])

  useEffect(() => {
    const controller = new AbortController()

    async function run() {
      while (!controller.signal.aborted) {
        let opened = false
        try {
          const response = await openReviewStream(token, reviewId, controller.signal)
          opened = true
          setConnectionStatus('ready')
          for await (const event of parseEventStream(response)) {
            if (event.type === 'status') {
              const status = JSON.parse(event.data)
              setJob(status)
              if (status.agent_entries) {
                setAgentProgress((previous) => mergePersistedAgentEntries(previous, status.agent_entries))
              }
              continue
            }
            if (event.type === 'agent') {
              const agentEvent = JSON.parse(event.data)
              setAgentProgress((previous) => ({
                ...previous,
                [agentEvent.file_path]: { ...previous[agentEvent.file_path], [agentEvent.code_key]: agentEvent.entry },
              }))
              continue
            }
            const fileEvent = JSON.parse(event.data)
            setReviewedFiles((previous) => new Set(previous).add(fileEvent.file_path))
            if (fileEvent.failed) {
              setFailedFiles((previous) => new Set(previous).add(fileEvent.file_path))
            }
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
            setConnectionStatus('error')
            return
          }
        }
        if (controller.signal.aborted || TERMINAL_STATUSES.has(jobStatusRef.current)) {
          return
        }
        await new Promise((resolve) => setTimeout(resolve, STREAM_RECONNECT_DELAY_MS))
      }
    }

    run()
    return () => controller.abort()
  }, [token, reviewId, onUnauthorized])

  return { job, reviewedFiles, failedFiles, agentProgress, connectionStatus }
}

function mergePersistedAgentEntries(liveAgentProgress, persistedAgentEntries) {
  const merged = { ...liveAgentProgress }
  for (const [filePath, agents] of Object.entries(persistedAgentEntries)) {
    merged[filePath] = { ...agents, ...(merged[filePath] ?? {}) }
  }
  return merged
}
