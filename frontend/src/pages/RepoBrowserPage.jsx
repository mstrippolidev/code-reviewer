import { useCallback, useEffect, useRef, useState } from 'react'
import { FileTree } from '../components/FileTree'
import {
  RegisterRepoError,
  RepoFetchError,
  TOKEN_STORAGE_KEY,
  UnauthorizedError,
  fetchRegisteredRepos,
  fetchUserRepos,
  openIndexedFilesStream,
  registerRepo,
} from '../api/client'
import { parseEventStream } from '../api/sse'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'
import { buildFileTree } from '../utils/buildFileTree'

const POLL_INTERVAL_MS = 1500
const STREAM_RECONNECT_DELAY_MS = 1500
const TERMINAL_REPO_STATUSES = new Set(['indexed', 'failed'])
const TERMINAL_FILE_STATUSES = new Set(['indexed', 'skipped', 'failed'])
const STATUS_PROGRESS_PERCENT_BEFORE_FILES_APPEAR = { pending: 5, indexing: 10, indexed: 100, failed: 100 }

function useGithubRepos(token, onUnauthorized) {
  const [repos, setRepos] = useState([])
  const [status, setStatus] = useState('loading')

  useEffect(() => {
    fetchUserRepos(token)
      .then((fetchedRepos) => {
        setRepos(fetchedRepos)
        setStatus('ready')
      })
      .catch((error) => {
        if (error instanceof UnauthorizedError) {
          onUnauthorized()
          return
        }
        setStatus(error instanceof RepoFetchError ? 'error' : 'unauthenticated')
      })
  }, [token, onUnauthorized])

  return { repos, status }
}

function useRegisteredRepos(token, onUnauthorized) {
  const [registeredRepos, setRegisteredRepos] = useState([])
  const [hasError, setHasError] = useState(false)

  const refresh = useCallback(() => {
    fetchRegisteredRepos(token)
      .then((fetchedRepos) => {
        setRegisteredRepos(fetchedRepos)
        setHasError(false)
      })
      .catch((error) => {
        if (error instanceof UnauthorizedError) {
          onUnauthorized()
          return
        }
        setHasError(true)
      })
  }, [token, onUnauthorized])

  useEffect(refresh, [refresh])

  return { registeredRepos, refresh, hasError }
}

function upsertByFilePath(files, incomingFile) {
  const index = files.findIndex((file) => file.file_path === incomingFile.file_path)
  if (index === -1) {
    return [...files, incomingFile]
  }
  const next = [...files]
  next[index] = incomingFile
  return next
}

function useRepoFileTree(token, repoId, onUnauthorized) {
  const [trackedRepoId, setTrackedRepoId] = useState(repoId)
  const [files, setFiles] = useState([])
  const [status, setStatus] = useState(repoId ? 'loading' : 'idle')
  const [retryNonce, setRetryNonce] = useState(0)

  if (trackedRepoId !== repoId) {
    setTrackedRepoId(repoId)
    setFiles([])
    setStatus(repoId ? 'loading' : 'idle')
  }

  const allFilesSettled = files.length > 0 && files.every((file) => TERMINAL_FILE_STATUSES.has(file.status))
  const allFilesSettledRef = useRef(allFilesSettled)
  useEffect(() => {
    allFilesSettledRef.current = allFilesSettled
  }, [allFilesSettled])

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
          for await (const rawData of parseEventStream(response)) {
            const file = JSON.parse(rawData)
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
        if (controller.signal.aborted || allFilesSettledRef.current) {
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
  const nodes = buildFileTree(files.map((file) => ({ path: file.file_path, status: file.status })))
  return { nodes, status, totalFileCount: files.length, settledFileCount, refresh }
}

function notEnoughPythonReason(repo) {
  return `Not enough Python (${repo.python_percentage}%)`
}

function byAlreadyRegisteredFirst(registeredRepoIds) {
  return (a, b) => Number(registeredRepoIds.has(b.repo_id)) - Number(registeredRepoIds.has(a.repo_id))
}

function computeProgressPercent(repoStatus, totalFileCount, settledFileCount) {
  if (totalFileCount > 0) {
    return Math.round((settledFileCount / totalFileCount) * 100)
  }
  return STATUS_PROGRESS_PERCENT_BEFORE_FILES_APPEAR[repoStatus] ?? 0
}

export function RepoBrowserPage() {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const handleUnauthorized = useUnauthorizedHandler()
  const { repos, status } = useGithubRepos(token, handleUnauthorized)
  const { registeredRepos, refresh, hasError: registeredReposError } = useRegisteredRepos(token, handleUnauthorized)
  const [selectedRepoId, setSelectedRepoId] = useState(null)
  const [registeringRepoId, setRegisteringRepoId] = useState(null)
  const [registerError, setRegisterError] = useState(null)
  const [viewedRepoId, setViewedRepoId] = useState(null)
  const [notAvailableExpanded, setNotAvailableExpanded] = useState(false)

  const registeredRepoIds = new Set(registeredRepos.map((repo) => repo.repo_id))
  const registeringRepo = registeredRepos.find((repo) => repo.repo_id === registeringRepoId) ?? null
  const viewedRepo = registeredRepos.find((repo) => repo.repo_id === viewedRepoId) ?? null
  const {
    nodes: fileTreeNodes,
    status: fileTreeStatus,
    totalFileCount,
    settledFileCount,
    refresh: refreshFileTree,
  } = useRepoFileTree(token, viewedRepoId, handleUnauthorized)

  function handleRetryClick() {
    refresh()
    refreshFileTree()
  }

  useEffect(() => {
    if (!registeringRepoId || registeredReposError || (registeringRepo && TERMINAL_REPO_STATUSES.has(registeringRepo.status))) {
      return
    }
    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [registeringRepoId, registeringRepo, registeredReposError, refresh])

  if (status === 'loading') {
    return <p className="page centered">Loading your repositories...</p>
  }
  if (status === 'unauthenticated') {
    return <p className="page centered">No access token found. Please log in again.</p>
  }
  if (status === 'error') {
    return <p className="page centered">Could not load your GitHub repositories.</p>
  }

  const selectedRepo = repos.find((repo) => repo.repo_id === selectedRepoId) ?? null
  const selectedRepoIsRegistered = selectedRepo ? registeredRepoIds.has(selectedRepo.repo_id) : false
  const validRepos = repos.filter((repo) => repo.has_enough_python).sort(byAlreadyRegisteredFirst(registeredRepoIds))
  const notAvailableRepos = repos.filter((repo) => !repo.has_enough_python)

  async function handlePrimaryAction() {
    if (!selectedRepo) {
      return
    }
    if (selectedRepoIsRegistered) {
      setViewedRepoId(selectedRepo.repo_id)
      return
    }
    setRegisterError(null)
    try {
      const registered = await registerRepo(token, { repo_id: selectedRepo.repo_id, full_name: selectedRepo.full_name })
      setRegisteringRepoId(registered.repo_id)
      setViewedRepoId(registered.repo_id)
      refresh()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setRegisterError(error instanceof RegisterRepoError ? error.message : 'Could not register this repo.')
    }
  }

  return (
    <div className="repo-browser">
      <div className="repo-browser-pane repo-browser-left">
        <h1>Select a repository to register</h1>
        <ul className="repo-list">
          {validRepos.map((repo) => {
            const isAlreadyRegistered = registeredRepoIds.has(repo.repo_id)
            return (
              <li key={repo.repo_id} className={repo.repo_id === viewedRepoId ? 'repo-viewing' : ''}>
                <label>
                  <input
                    type="radio"
                    name="selected_repo"
                    checked={selectedRepoId === repo.repo_id}
                    onChange={() => setSelectedRepoId(repo.repo_id)}
                  />
                  {repo.full_name}
                  {repo.private ? ' (private)' : ''}
                  {isAlreadyRegistered ? <span className="repo-tag"> (already registered)</span> : null}
                </label>
              </li>
            )
          })}
        </ul>
        {notAvailableRepos.length > 0 ? (
          <div className="repo-section-collapsible">
            <button
              type="button"
              className="repo-section-toggle"
              aria-expanded={notAvailableExpanded}
              onClick={() => setNotAvailableExpanded((expanded) => !expanded)}
            >
              <span className={`repo-section-arrow${notAvailableExpanded ? ' expanded' : ''}`}>▸</span>
              Not available ({notAvailableRepos.length})
            </button>
            {notAvailableExpanded ? (
              <ul className="repo-list repo-list-readonly">
                {notAvailableRepos.map((repo) => (
                  <li key={repo.repo_id} className="repo-disabled">
                    {repo.full_name}
                    {repo.private ? ' (private)' : ''}
                    <span className="repo-reason"> — {notEnoughPythonReason(repo)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <button
          className={`button${selectedRepo && !registeringRepoId ? '' : ' disabled'}`}
          type="button"
          disabled={!selectedRepo || Boolean(registeringRepoId)}
          onClick={handlePrimaryAction}
        >
          Continue
        </button>
      </div>
      <div className="repo-browser-pane repo-browser-right">
        {registerError ? <p className="note error">{registerError}</p> : null}
        {viewedRepo ? (
          <div className="repo-progress">
            <div className="repo-progress-header">
              <p className="repo-progress-label">
                {viewedRepo.full_name}: {viewedRepo.status}
                {viewedRepo.status_reason ? ` — ${viewedRepo.status_reason}` : ''}
                {totalFileCount > 0 ? ` (${settledFileCount}/${totalFileCount} files)` : ''}
              </p>
              <button type="button" className="repo-refresh-button" onClick={handleRetryClick}>
                ⟳ Refresh
              </button>
            </div>
            <div className="repo-progress-bar">
              <div
                className={`repo-progress-fill repo-progress-${viewedRepo.status}`}
                style={{ width: `${computeProgressPercent(viewedRepo.status, totalFileCount, settledFileCount)}%` }}
              />
            </div>
          </div>
        ) : null}
        {!viewedRepoId ? (
          registerError ? null : <p className="note">Register or select a repo to see its indexed files.</p>
        ) : fileTreeStatus === 'error' ? (
          <p className="note error">Could not load this repo's indexed files.</p>
        ) : fileTreeNodes.length === 0 ? (
          <p className="note">No files indexed yet.</p>
        ) : (
          <FileTree nodes={fileTreeNodes} />
        )}
      </div>
    </div>
  )
}
