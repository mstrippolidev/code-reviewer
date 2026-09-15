import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  RegisterRepoError,
  RepoFetchError,
  TOKEN_STORAGE_KEY,
  fetchRegisteredRepos,
  fetchUserRepos,
  registerRepo,
} from '../api/client'

const POLL_INTERVAL_MS = 1500
const TERMINAL_STATUSES = new Set(['indexed', 'failed'])
const STATUS_PROGRESS_PERCENT = { pending: 25, indexing: 65, indexed: 100, failed: 100 }

function useAccessToken() {
  const [searchParams] = useSearchParams()
  const tokenFromUrl = searchParams.get('token')
  if (tokenFromUrl) {
    localStorage.setItem(TOKEN_STORAGE_KEY, tokenFromUrl)
  }
  return tokenFromUrl ?? localStorage.getItem(TOKEN_STORAGE_KEY)
}

function useGithubRepos(token) {
  const [repos, setRepos] = useState([])
  const [status, setStatus] = useState(token ? 'loading' : 'unauthenticated')

  useEffect(() => {
    if (!token) {
      return
    }
    fetchUserRepos(token)
      .then((fetchedRepos) => {
        setRepos(fetchedRepos)
        setStatus('ready')
      })
      .catch((error) => {
        setStatus(error instanceof RepoFetchError ? 'error' : 'unauthenticated')
      })
  }, [token])

  return { repos, status }
}

function useRegisteredRepos(token) {
  const [registeredRepos, setRegisteredRepos] = useState([])

  const refresh = useCallback(() => {
    if (!token) {
      return
    }
    fetchRegisteredRepos(token).then(setRegisteredRepos).catch(() => {})
  }, [token])

  useEffect(refresh, [refresh])

  return { registeredRepos, refresh }
}

function disabledReason(repo, registeredRepoIds) {
  if (registeredRepoIds.has(repo.repo_id)) {
    return 'Already registered'
  }
  if (!repo.has_enough_python) {
    return `Not enough Python (${repo.python_percentage}%)`
  }
  return null
}

export function CallbackPage() {
  const token = useAccessToken()
  const { repos, status } = useGithubRepos(token)
  const { registeredRepos, refresh } = useRegisteredRepos(token)
  const [selectedRepoId, setSelectedRepoId] = useState(null)
  const [registeringRepoId, setRegisteringRepoId] = useState(null)
  const [registerError, setRegisterError] = useState(null)

  const registeredRepoIds = new Set(registeredRepos.map((repo) => repo.repo_id))
  const registeringRepo = registeredRepos.find((repo) => repo.repo_id === registeringRepoId) ?? null

  useEffect(() => {
    if (!registeringRepoId || (registeringRepo && TERMINAL_STATUSES.has(registeringRepo.status))) {
      return
    }
    const interval = setInterval(refresh, POLL_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [registeringRepoId, registeringRepo, refresh])

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

  async function handleRegister() {
    if (!selectedRepo) {
      return
    }
    setRegisterError(null)
    try {
      const registered = await registerRepo(token, { repo_id: selectedRepo.repo_id, full_name: selectedRepo.full_name })
      setRegisteringRepoId(registered.repo_id)
      refresh()
    } catch (error) {
      setRegisterError(error instanceof RegisterRepoError ? error.message : 'Could not register this repo.')
    }
  }

  return (
    <div className="page">
      <h1>Select a repository to register</h1>
      <ul className="repo-list">
        {repos.map((repo) => {
          const reason = disabledReason(repo, registeredRepoIds)
          const disabled = reason !== null
          return (
            <li key={repo.repo_id} className={disabled ? 'repo-disabled' : ''}>
              <label>
                <input
                  type="radio"
                  name="selected_repo"
                  checked={selectedRepoId === repo.repo_id}
                  disabled={disabled}
                  onChange={() => setSelectedRepoId(repo.repo_id)}
                />
                {repo.full_name}
                {repo.private ? ' (private)' : ''}
                {reason ? <span className="repo-reason"> — {reason}</span> : null}
              </label>
            </li>
          )
        })}
      </ul>
      <button
        className={`button${selectedRepo && !registeringRepoId ? '' : ' disabled'}`}
        type="button"
        disabled={!selectedRepo || Boolean(registeringRepoId)}
        onClick={handleRegister}
      >
        Register selected repo
      </button>
      {registerError ? <p className="note error">{registerError}</p> : null}
      {registeringRepo ? (
        <div className="registration-progress">
          <div className="progress-bar">
            <div
              className={`progress-bar-fill progress-${registeringRepo.status}`}
              style={{ width: `${STATUS_PROGRESS_PERCENT[registeringRepo.status] ?? 0}%` }}
            />
          </div>
          <p className="note">
            {registeringRepo.full_name}: {registeringRepo.status}
            {registeringRepo.status_reason ? ` — ${registeringRepo.status_reason}` : ''}
          </p>
        </div>
      ) : null}
    </div>
  )
}
