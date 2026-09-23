const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
export const TOKEN_STORAGE_KEY = 'access_token'

export class RepoFetchError extends Error {}

export class RegisterRepoError extends Error {}

export class RepoIndexingControlError extends Error {}

export class RepoBranchFetchError extends Error {}

export class SubmitReviewError extends Error {}

export class AgentCatalogFetchError extends Error {}

export class FileContentFetchError extends Error {}

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

export async function registerRepo(token, { repo_id: repoId, full_name: fullName, branch }) {
  const response = await fetch(`${API_BASE_URL}/api/repos`, {
    method: 'POST',
    headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
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

export async function fetchRepoBranches(token, fullName) {
  return getJson(
    `${API_BASE_URL}/api/oauth/github/repos/branches?full_name=${encodeURIComponent(fullName)}`,
    token,
    RepoBranchFetchError
  )
}

export async function switchRepoBranch(token, repoId, branch) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/branch`, {
    method: 'POST',
    headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
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

export async function resumeRepoIndexing(token, repoId) {
  return postRepoControl(token, `${API_BASE_URL}/api/repos/${repoId}/resume`)
}

export async function retryFailedFiles(token, repoId) {
  return postRepoControl(token, `${API_BASE_URL}/api/repos/${repoId}/files/retry`)
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

export async function submitReview(token, repoId, filePaths) {
  const response = await fetch(`${API_BASE_URL}/api/repos/${repoId}/review`, {
    method: 'POST',
    headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
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

export async function fetchReview(token, reviewId) {
  return getJson(`${API_BASE_URL}/api/reviews/${reviewId}`, token, SubmitReviewError)
}

export async function fetchAgents(token) {
  return getJson(`${API_BASE_URL}/api/agents`, token, AgentCatalogFetchError)
}

export async function fetchIndexedFileContent(token, repoId, filePath) {
  return getJson(
    `${API_BASE_URL}/api/repos/${repoId}/files/content?file_path=${encodeURIComponent(filePath)}`,
    token,
    FileContentFetchError
  )
}

export async function openReviewStream(token, reviewId, signal) {
  const response = await fetch(`${API_BASE_URL}/api/reviews/${reviewId}/stream`, {
    headers: authHeaders(token),
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
