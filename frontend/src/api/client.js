const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
export const TOKEN_STORAGE_KEY = 'access_token'

export class RepoFetchError extends Error {}

export class RegisterRepoError extends Error {}

export function githubLoginUrl(accessLevel) {
  return `${API_BASE_URL}/api/oauth/github/login?access_level=${accessLevel}`
}

export async function fetchUserRepos(token) {
  const response = await fetch(`${API_BASE_URL}/api/oauth/github/repos`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new RepoFetchError(`Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function fetchRegisteredRepos(token) {
  const response = await fetch(`${API_BASE_URL}/api/repos`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new RepoFetchError(`Request failed with status ${response.status}`)
  }
  return response.json()
}

export async function registerRepo(token, { repo_id: repoId, full_name: fullName }) {
  const response = await fetch(`${API_BASE_URL}/api/repos`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_id: repoId, full_name: fullName }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new RegisterRepoError(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json()
}
