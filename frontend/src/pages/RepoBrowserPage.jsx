import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BranchSelect } from '../components/BranchSelect'
import { ConfirmModal } from '../components/ConfirmModal'
import { FileTree } from '../components/FileTree'
import { ReviewSelectionZone } from '../components/ReviewSelectionZone'
import {
  RegisterRepoError,
  RepoFetchError,
  RepoIndexingControlError,
  SubmitReviewError,
  TOKEN_STORAGE_KEY,
  UnauthorizedError,
  deleteRepo,
  fetchRegisteredRepos,
  fetchUserRepos,
  registerRepo,
  resumeRepoIndexing,
  retryFailedFiles,
  submitReview,
  switchRepoBranch,
} from '../api/client'
import { useFileSelection } from '../hooks/useFileSelection'
import { useRepoFileTree, RESTING_REPO_STATUSES } from '../hooks/useRepoFileTree'
import { useUnauthorizedHandler } from '../hooks/useUnauthorizedHandler'

const REPO_PAGE_SIZE = 10
const FINISHED_REPO_STATUSES = new Set(['completed', 'failed'])
const STATUS_PROGRESS_PERCENT_BEFORE_FILES_APPEAR = { pending: 5, indexing: 10, completed: 100, failed: 100 }
const MAX_REVIEW_FILES = 15 // mirrors .env's MAX_FILES_PER_SUBMISSION

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
  const navigate = useNavigate()
  const handleUnauthorized = useUnauthorizedHandler()
  const { repos, status } = useGithubRepos(token, handleUnauthorized)
  const { registeredRepos, refresh } = useRegisteredRepos(token, handleUnauthorized)
  const [selectedRepoId, setSelectedRepoId] = useState(null)
  const [registeringRepoId, setRegisteringRepoId] = useState(null)
  const [registerError, setRegisterError] = useState(null)
  const [viewedRepoId, setViewedRepoId] = useState(null)
  const [notAvailableExpanded, setNotAvailableExpanded] = useState(false)
  const [controlError, setControlError] = useState(null)
  const [repoPage, setRepoPage] = useState(0)
  const [pendingRegisterRepo, setPendingRegisterRepo] = useState(null)
  const [registerBranch, setRegisterBranch] = useState(null)
  const [pendingDeleteRepo, setPendingDeleteRepo] = useState(null)
  const [pendingBranchSwitch, setPendingBranchSwitch] = useState(null)
  const [submittingReview, setSubmittingReview] = useState(false)
  const [reviewError, setReviewError] = useState(null)
  const [pendingReviewSubmit, setPendingReviewSubmit] = useState(false)
  const { selectedFiles, toggleNode: handleToggleSelect, addPath: handleDropFile, removePath: handleRemoveFile } =
    useFileSelection(viewedRepoId, MAX_REVIEW_FILES)

  const registeredRepoIds = new Set(registeredRepos.map((repo) => repo.repo_id))
  const baseViewedRepo = registeredRepos.find((repo) => repo.repo_id === viewedRepoId) ?? null
  const {
    nodes: fileTreeNodes,
    status: fileTreeStatus,
    repoStatus: liveRepoStatus,
    settledFileCount,
    failedFileCount,
    refresh: refreshFileTree,
  } = useRepoFileTree(token, viewedRepoId, handleUnauthorized)
  const viewedRepo = baseViewedRepo && liveRepoStatus ? { ...baseViewedRepo, ...liveRepoStatus } : baseViewedRepo
  const isFinished = viewedRepo ? FINISHED_REPO_STATUSES.has(viewedRepo.status) : false

  async function handleSubmitReview() {
    setReviewError(null)
    setSubmittingReview(true)
    try {
      const job = await submitReview(token, viewedRepo.repo_id, [...selectedFiles])
      navigate(`/reviews/${job.review_id}`)
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setReviewError(error instanceof SubmitReviewError ? error.message : 'Could not submit this review.')
    } finally {
      setSubmittingReview(false)
    }
  }

  async function handleRetryFailedClick() {
    setControlError(null)
    try {
      await retryFailedFiles(token, viewedRepo.repo_id)
      refresh()
      refreshFileTree()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setControlError(error instanceof RepoIndexingControlError ? error.message : 'Could not retry failed files.')
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

  function handleDeleteClick() {
    setPendingDeleteRepo(viewedRepo)
  }

  async function handleConfirmDelete() {
    const repo = pendingDeleteRepo
    setPendingDeleteRepo(null)
    setControlError(null)
    try {
      await deleteRepo(token, repo.repo_id)
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

  async function handleConfirmBranchSwitch() {
    const branch = pendingBranchSwitch
    setPendingBranchSwitch(null)
    setControlError(null)
    try {
      await switchRepoBranch(token, viewedRepo.repo_id, branch)
      refresh()
      refreshFileTree()
    } catch (error) {
      if (error instanceof UnauthorizedError) {
        handleUnauthorized()
        return
      }
      setControlError(error instanceof RepoIndexingControlError ? error.message : 'Could not switch branches.')
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
  const repoPageCount = Math.max(1, Math.ceil(validRepos.length / REPO_PAGE_SIZE))
  const currentRepoPage = Math.min(repoPage, repoPageCount - 1)
  const pagedValidRepos = validRepos.slice(
    currentRepoPage * REPO_PAGE_SIZE,
    currentRepoPage * REPO_PAGE_SIZE + REPO_PAGE_SIZE
  )

  function handlePrimaryAction() {
    if (!selectedRepo) {
      return
    }
    if (selectedRepoIsRegistered) {
      setViewedRepoId(selectedRepo.repo_id)
      return
    }
    setRegisterBranch(selectedRepo.default_branch)
    setPendingRegisterRepo(selectedRepo)
  }

  async function handleConfirmRegister() {
    const repo = pendingRegisterRepo
    const branch = registerBranch
    setPendingRegisterRepo(null)
    setRegisterError(null)
    try {
      const registered = await registerRepo(token, { repo_id: repo.repo_id, full_name: repo.full_name, branch })
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

  function handleCancelRegister() {
    setPendingRegisterRepo(null)
    setRegisterBranch(null)
  }

  const showSelectionZone = viewedRepoId && fileTreeStatus !== 'error' && fileTreeNodes.length > 0

  return (
    <div className="repo-browser">
      <div className="repo-browser-top">
        <div className="repo-browser-pane repo-browser-left">
          <h1>Select a repository to register</h1>
          <div className="repo-list-scroll">
            <ul className="repo-list">
              {pagedValidRepos.map((repo) => {
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
            {repoPageCount > 1 ? (
              <div className="repo-pagination">
                <button
                  type="button"
                  className="repo-control-button"
                  disabled={currentRepoPage === 0}
                  onClick={() => setRepoPage((page) => page - 1)}
                >
                  ‹ Prev
                </button>
                <span className="repo-pagination-label">
                  Page {currentRepoPage + 1} of {repoPageCount}
                </span>
                <button
                  type="button"
                  className="repo-control-button"
                  disabled={currentRepoPage >= repoPageCount - 1}
                  onClick={() => setRepoPage((page) => page + 1)}
                >
                  Next ›
                </button>
              </div>
            ) : null}
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
          </div>
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
          <h2 className="repo-browser-right-title">Indexed files</h2>
          {registerError ? <p className="note error">{registerError}</p> : null}
          {controlError ? <p className="note error">{controlError}</p> : null}
          {reviewError ? <p className="note error">{reviewError}</p> : null}
          {viewedRepo ? (
            <div className="repo-progress">
              <div className="repo-progress-header">
                <p className="repo-progress-label">
                  {viewedRepo.full_name}
                  <span className={`status-pill status-pill-${viewedRepo.status}`}>{viewedRepo.status}</span>
                  {viewedRepo.status_reason ? ` — ${viewedRepo.status_reason}` : ''}
                  {viewedRepo.total_files_expected ? ` (${settledFileCount}/${viewedRepo.total_files_expected} files)` : ''}
                </p>
                <div className="repo-progress-actions">
                  <BranchSelect
                    token={token}
                    fullName={viewedRepo.full_name}
                    value={viewedRepo.branch}
                    disabled={!isFinished}
                    onChange={(branch) => branch !== viewedRepo.branch && setPendingBranchSwitch(branch)}
                  />
                  {viewedRepo.status === 'paused' ? (
                    <button type="button" className="repo-control-button" onClick={handleResumeClick}>
                      Resume
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="repo-control-button repo-control-button-danger"
                    disabled={!isFinished}
                    onClick={handleDeleteClick}
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    className="repo-refresh-button"
                    disabled={!isFinished}
                    onClick={handleRetryFailedClick}
                    title={
                      isFinished
                        ? failedFileCount > 0
                          ? `Retry ${failedFileCount} failed file(s)`
                          : 'No failed files to retry'
                        : 'Available once indexing finishes'
                    }
                  >
                    ⟳ Retry failed
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
            <div className="file-tree-scroll">
              <FileTree nodes={fileTreeNodes} selectedPaths={selectedFiles} onToggleSelect={handleToggleSelect} />
            </div>
          )}
        </div>
      </div>
      {showSelectionZone ? (
        <ReviewSelectionZone
          selectedPaths={selectedFiles}
          max={MAX_REVIEW_FILES}
          submitting={submittingReview}
          onRemove={handleRemoveFile}
          onDropFile={handleDropFile}
          onSubmit={() => setPendingReviewSubmit(true)}
        />
      ) : null}
      {pendingReviewSubmit ? (
        <ConfirmModal
          confirmLabel="Start review"
          onConfirm={() => {
            setPendingReviewSubmit(false)
            handleSubmitReview()
          }}
          onCancel={() => setPendingReviewSubmit(false)}
        >
          <p>
            Reviewing <strong>{selectedFiles.size}</strong> file(s) can take several minutes — 14 agents run
            against each file. You can keep using the app while it runs in the background.
          </p>
        </ConfirmModal>
      ) : null}
      {pendingRegisterRepo ? (
        <ConfirmModal confirmLabel="Continue" onConfirm={handleConfirmRegister} onCancel={handleCancelRegister}>
          <p>
            Indexing <strong>{pendingRegisterRepo.full_name}</strong> can take several minutes. You can keep
            using the app while it runs in the background.
          </p>
          <BranchSelect
            token={token}
            fullName={pendingRegisterRepo.full_name}
            value={registerBranch}
            onChange={setRegisterBranch}
          />
        </ConfirmModal>
      ) : null}
      {pendingDeleteRepo ? (
        <ConfirmModal
          confirmLabel="Delete"
          danger
          onConfirm={handleConfirmDelete}
          onCancel={() => setPendingDeleteRepo(null)}
        >
          <p>
            Delete <strong>{pendingDeleteRepo.full_name}</strong>? This removes its registration and its
            indexed files from the database. This cannot be undone.
          </p>
        </ConfirmModal>
      ) : null}
      {pendingBranchSwitch ? (
        <ConfirmModal
          confirmLabel="Switch branch"
          danger
          onConfirm={handleConfirmBranchSwitch}
          onCancel={() => setPendingBranchSwitch(null)}
        >
          <p>
            Switch <strong>{viewedRepo.full_name}</strong> to <strong>{pendingBranchSwitch}</strong>? This deletes
            the current index and re-indexes from scratch.
          </p>
        </ConfirmModal>
      ) : null}
    </div>
  )
}
