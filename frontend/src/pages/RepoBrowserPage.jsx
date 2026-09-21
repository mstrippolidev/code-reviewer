import { useCallback, useEffect, useRef, useState } from 'react'
import { FileTree } from '../components/FileTree'
import {
  RegisterRepoError,
  RepoFetchError,
  RepoIndexingControlError,
  TOKEN_STORAGE_KEY,
  UnauthorizedError,
  deleteRepo,
  fetchRegisteredRepos,
  fetchUserRepos,
  openIndexedFilesStream,
  pauseRepoIndexing,
  registerRepo,
  resumeRepoIndexing,
} from '../api/client'
import { parseEventStream } from '../api/sse'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'
import { buildFileTree } from '../utils/buildFileTree'

const STREAM_RECONNECT_DELAY_MS = 1500
const RESTING_REPO_STATUSES = new Set(['completed', 'failed', 'paused'])
const TERMINAL_FILE_STATUSES = new Set(['indexed', 'skipped', 'failed'])
const STATUS_PROGRESS_PERCENT_BEFORE_FILES_APPEAR = { pending: 5, indexing: 10, completed: 100, failed: 100 }

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
  const nodes = buildFileTree(files.map((file) => ({ path: file.file_path, status: file.status })))
  return { nodes, status, repoStatus, totalFileCount: files.length, settledFileCount, refresh }
}

function notEnoughPythonReason(repo) {
  return `Not enough Python (${repo.python_percentage}%)`
}

function byAlreadyRegisteredFirst(registeredRepoIds) {
  return (a, b) => Number(registeredRepoIds.has(b.repo_id)) - Number(registeredRepoIds.has(a.repo_id))
}

function computeProgressPercent(repo, settledFileCount) {
  if (repo.total_files_expected) {
    return Math.round((settledFileCount / repo.total_files_expected) * 100)
  }
  return STATUS_PROGRESS_PERCENT_BEFORE_FILES_APPEAR[repo.status] ?? 0
}

export function RepoBrowserPage() {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  const handleUnauthorized = useUnauthorizedHandler()
  const { repos, status } = useGithubRepos(token, handleUnauthorized)
  const { registeredRepos, refresh } = useRegisteredRepos(token, handleUnauthorized)
  const [selectedRepoId, setSelectedRepoId] = useState(null)
  const [registeringRepoId, setRegisteringRepoId] = useState(null)
  const [registerError, setRegisterError] = useState(null)
  const [viewedRepoId, setViewedRepoId] = useState(null)
  const [notAvailableExpanded, setNotAvailableExpanded] = useState(false)
  const [controlError, setControlError] = useState(null)

  const registeredRepoIds = new Set(registeredRepos.map((repo) => repo.repo_id))
  const baseViewedRepo = registeredRepos.find((repo) => repo.repo_id === viewedRepoId) ?? null
  const {
    nodes: fileTreeNodes,
    status: fileTreeStatus,
    repoStatus: liveRepoStatus,
    settledFileCount,
    refresh: refreshFileTree,
  } = useRepoFileTree(token, viewedRepoId, handleUnauthorized)
  const viewedRepo = baseViewedRepo && liveRepoStatus ? { ...baseViewedRepo, ...liveRepoStatus } : baseViewedRepo

  function handleRetryClick() {
    refresh()
    refreshFileTree()
  }

  async function handlePauseClick() {
    setControlError(null)
    try {
      await pauseRepoIndexing(token, viewedRepo.repo_id)
      refresh()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setControlError(error instanceof RepoIndexingControlError ? error.message : 'Could not pause indexing.')
    }
  }

  async function handleResumeClick() {
    setControlError(null)
    try {
      await resumeRepoIndexing(token, viewedRepo.repo_id)
      refresh()
      refreshFileTree()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setControlError(error instanceof RepoIndexingControlError ? error.message : 'Could not resume indexing.')
    }
  }

  async function handleDeleteClick() {
    if (!window.confirm(`Delete ${viewedRepo.full_name} and all its indexed content? This cannot be undone.`)) {
      return
    }
    setControlError(null)
    try {
      await deleteRepo(token, viewedRepo.repo_id)
      setViewedRepoId(null)
      refresh()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setControlError(error instanceof RepoIndexingControlError ? error.message : 'Could not delete this repo.')
    }
  }

  useEffect(() => {
    if (liveRepoStatus && RESTING_REPO_STATUSES.has(liveRepoStatus.status)) {
      refresh()
    }
  }, [liveRepoStatus?.status, refresh])

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
        {controlError ? <p className="note error">{controlError}</p> : null}
        {viewedRepo ? (
          <div className="repo-progress">
            <div className="repo-progress-header">
              <p className="repo-progress-label">
                {viewedRepo.full_name}: {viewedRepo.status}
                {viewedRepo.status_reason ? ` — ${viewedRepo.status_reason}` : ''}
                {viewedRepo.total_files_expected ? ` (${settledFileCount}/${viewedRepo.total_files_expected} files)` : ''}
              </p>
              <div className="repo-progress-actions">
                {viewedRepo.status === 'indexing' ? (
                  <button type="button" className="repo-control-button" onClick={handlePauseClick}>
                    Stop
                  </button>
                ) : null}
                {viewedRepo.status === 'paused' ? (
                  <button type="button" className="repo-control-button" onClick={handleResumeClick}>
                    Resume
                  </button>
                ) : null}
                <button type="button" className="repo-control-button repo-control-button-danger" onClick={handleDeleteClick}>
                  Delete
                </button>
                <button type="button" className="repo-refresh-button" onClick={handleRetryClick}>
                  ⟳ Refresh
                </button>
              </div>
            </div>
            <div className="repo-progress-bar">
              <div
                className={`repo-progress-fill repo-progress-${viewedRepo.status}`}
                style={{ width: `${computeProgressPercent(viewedRepo, settledFileCount)}%` }}
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
