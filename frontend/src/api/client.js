const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
export const TOKEN_STORAGE_KEY = 'access_token'

export class RepoFetchError extends Error {}

export class RegisterRepoError extends Error {}

export class RepoIndexingControlError extends Error {}

export class UnauthorizedError extends Error {}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` }
}

async function getJson(url, token, ErrorClass) {
  const response = await fetch(url, { headers: authHeaders(token) })
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

export async function fetchUserRepos(token) {
  return getJson(`${API_BASE_URL}/api/oauth/github/repos`, token, RepoFetchError)
}

export async function fetchRegisteredRepos(token) {
  return getJson(`${API_BASE_URL}/api/repos`, token, RepoFetchError)
}

export async function openIndexedFilesStream(token, repoId, signal) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/files/stream`, {
    headers: authHeaders(token),
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

export async function registerRepo(token, { repo_id: repoId, full_name: fullName }) {
  const response = await fetch(`${API_BASE_URL}/api/repos`, {
    method: 'POST',
    headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_id: repoId, full_name: fullName }),
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

export async function pauseRepoIndexing(token, repoId) {
  return postRepoControl(token, `${API_BASE_URL}/api/repos/${repoId}/pause`)
}

export async function resumeRepoIndexing(token, repoId) {
  return postRepoControl(token, `${API_BASE_URL}/api/repos/${repoId}/resume`)
}

async function postRepoControl(token, url) {
  const response = await fetch(url, { method: 'POST', headers: authHeaders(token) })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RepoIndexingControlError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function deleteRepo(token, repoId) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}`, {
    method: 'DELETE',
    headers: authHeaders(token),
  })
  if (response.status === 401) {
    throw new UnauthorizedError('Session expired')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RepoIndexingControlError(body.detail ?? `Request failed with status ${response.status}`)
  }
}
