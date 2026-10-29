const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
// The guest cookie itself is httpOnly and invisible to JS; this flag only lets the
// router know a guest session was started, the server still verifies the cookie.
export const GUEST_STORAGE_KEY = 'guest_session'

export class RepoFetchError extends Error {}

export class RegisterRepoError extends Error {}

export class RepoIndexingControlError extends Error {}

export class RepoBranchFetchError extends Error {}

export class SubmitReviewError extends Error {}

export class AgentCatalogFetchError extends Error {}

export class FileContentFetchError extends Error {}

export class UnauthorizedError extends Error {}

export class GuestSessionError extends Error {}

// Identity rides on httpOnly cookies (user session or guest), which a cross-origin fetch
// only sends with credentials: 'include'.
async function getJson(url, ErrorClass, signal) {
  const response = await fetch(url, { credentials: 'include', signal })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    throw new ErrorClass(`Request failed with status ${response.status}`)
  }
  return response.json()
}

export function githubLoginUrl(accessLevel) {
  return `${API_BASE_URL}/api/oauth/github/login?access_level=${accessLevel}`
}

export async function fetchUserRepos() {
  return getJson(`${API_BASE_URL}/api/oauth/github/repos`, RepoFetchError)
}

export async function fetchRegisteredRepos() {
  return getJson(`${API_BASE_URL}/api/repos`, RepoFetchError)
}

export async function openIndexedFilesStream(repoId, signal) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/files/stream`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    throw new RepoFetchError(`Request failed with status ${response.status}`)
  }
  return response
}

export async function registerRepo({ repo_id: repoId, full_name: fullName, branch }) {
  const response = await fetch(`${API_BASE_URL}/api/repos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ repo_id: repoId, full_name: fullName, branch }),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RegisterRepoError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function fetchRepoBranches(fullName) {
  return getJson(
    `${API_BASE_URL}/api/oauth/github/repos/branches?full_name=${encodeURIComponent(fullName)}`,
    RepoBranchFetchError
  )
}

export async function switchRepoBranch(repoId, branch) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/branch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ branch }),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RepoIndexingControlError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function resumeRepoIndexing(repoId) {
  return postRepoControl(`${API_BASE_URL}/api/repos/${repoId}/resume`)
}

export async function retryFailedFiles(repoId) {
  return postRepoControl(`${API_BASE_URL}/api/repos/${repoId}/files/retry`)
}

async function postRepoControl(url) {
  const response = await fetch(url, { method: 'POST', credentials: 'include' })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RepoIndexingControlError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function deleteRepo(repoId) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RepoIndexingControlError(body.detail ?? `Request failed with status ${response.status}`)
  }
}

export async function submitReview(repoId, filePaths) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ file_paths: filePaths }),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new SubmitReviewError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function fetchAgents() {
  return getJson(`${API_BASE_URL}/api/agents`, AgentCatalogFetchError)
}

export async function fetchIndexedFileContent(repoId, filePath, signal) {
  return getJson(
    `${API_BASE_URL}/api/repos/${repoId}/files/content?file_path=${encodeURIComponent(filePath)}`,
    FileContentFetchError,
    signal
  )
}

export async function fetchReviewFileContent(reviewId, filePath, signal) {
  return getJson(
    `${API_BASE_URL}/api/reviews/${reviewId}/files/content?file_path=${encodeURIComponent(filePath)}`,
    FileContentFetchError,
    signal
  )
}

export async function startGuestSession() {
  const response = await fetch(`${API_BASE_URL}/api/guest/session`, { method: 'POST', credentials: 'include' })
  if (!response.ok) {
    throw new GuestSessionError(`Request failed with status ${response.status}`)
  }
}

export async function submitGuestReview(files) {
  const response = await fetch(`${API_BASE_URL}/api/guest/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ files }),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Guest session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : null
    throw new SubmitReviewError(detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export class OAuthConsentError extends Error {}

export async function fetchOAuthClient(clientId) {
  const response = await fetch(`${API_BASE_URL}/oauth/clients/${encodeURIComponent(clientId)}`)
  if (!response.ok) {
    throw new OAuthConsentError('This application is not registered')
  }
  return response.json()
}

export async function submitOAuthDecision(authorizeParams, approve) {
  const response = await fetch(`${API_BASE_URL}/oauth/authorize/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ ...authorizeParams, approve }),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new OAuthConsentError(body.error_description ?? `Request failed with status ${response.status}`)
  }
  const { redirect_to: redirectTo } = await response.json()
  return redirectTo
}

export async function openReviewStream(reviewId, signal) {
  const response = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/stream`, {
    credentials: 'include',
    signal,
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    throw new SubmitReviewError(`Request failed with status ${response.status}`)
  }
  return response
}

export class CurrentUserFetchError extends Error {}

export async function fetchCurrentUser() {
  const response = await fetch(`${API_BASE_URL}/api/oauth/github/me`, { credentials: 'include' })
  if (response.status === 401) {
    throw new UnauthorizedError('Not signed in')
  }
  if (!response.ok) {
    throw new CurrentUserFetchError(`Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function logout() {
  await fetch(`${API_BASE_URL}/api/oauth/github/logout`, { method: 'POST', credentials: 'include' })
}
