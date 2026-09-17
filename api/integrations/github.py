"""
    GitHub OAuth login integration: authorization URL, code exchange, and profile fetch.
"""
import asyncio
import urllib.parse
from dataclasses import dataclass
from enum import Enum

import httpx

from api.schemas.github import GitHubRepo, GitHubUserProfile


AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_PROFILE_URL = "https://api.github.com/user"
USER_REPOS_URL = "https://api.github.com/user/repos"
REPO_URL_TEMPLATE = "https://api.github.com/repos/{full_name}"
REPO_LANGUAGES_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/languages"
COMMIT_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/commits/{ref}"
TARBALL_URL_TEMPLATE = "https://api.github.com/repos/{full_name}/tarball/{ref}"
PYTHON_PERCENTAGE_THRESHOLD = 25.0
REPOS_PER_PAGE = 15
WARMUP_CONNECTION_COUNT = 16
REPO_INDEXING_REQUEST_TIMEOUT_SECONDS = 15.0


class GitHubRepoAccessLevel(str, Enum):
    """Which repos the OAuth grant should cover; GitHub has no scope for private-only access."""

    ALL = "all"
    PUBLIC = "public"


SCOPE_BY_ACCESS_LEVEL = {
    GitHubRepoAccessLevel.ALL: "repo read:user",
    GitHubRepoAccessLevel.PUBLIC: "public_repo read:user",
}


class GitHubOAuthLoginError(Exception):
    """Raised when GitHub rejects a code exchange or refuses to return an access token."""


class GitHubProfileFetchError(Exception):
    """Raised when the authenticated user's GitHub profile cannot be retrieved."""


class GitHubRepoFetchError(Exception):
    """Raised when the authenticated user's repo list cannot be retrieved."""


class GitHubCommitFetchError(Exception):
    """Raised when a branch's tip commit sha cannot be retrieved."""


class GitHubTarballFetchError(Exception):
    """Raised when a repo's tarball snapshot cannot be downloaded."""


@dataclass(frozen=True)
class GitHubOAuthConfig:
    """Configuration for GitHub OAuth integration."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def get_authorization_url(self, state: str, access_level: GitHubRepoAccessLevel) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": SCOPE_BY_ACCESS_LEVEL[access_level],
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


@dataclass(frozen=True)
class GitHubTokenGrant:
    """Access token plus the scopes actually granted — may be fewer than requested."""

    access_token: str
    granted_scopes: str


class GitHubOAuthClient:
    """Talks to GitHub's OAuth and REST APIs to log a user in via GitHub."""

    def __init__(self, config: GitHubOAuthConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client

    def build_authorize_url(self, *, state: str, access_level: GitHubRepoAccessLevel) -> str:
        return self._config.get_authorization_url(state, access_level)

    async def exchange_code_for_token(self, code: str) -> GitHubTokenGrant:
        data = {
            "client_id": self._config.client_id,
            "client_secret": self._config.client_secret,
            "code": code,
            "redirect_uri": self._config.redirect_uri,
        }
        try:
            response = await self._client.post(ACCESS_TOKEN_URL, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as error:
            raise GitHubOAuthLoginError("Could not reach GitHub to exchange the OAuth code") from error
        return self._parse_token_grant(response)

    def _parse_token_grant(self, response: httpx.Response) -> GitHubTokenGrant:
        token_data = response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            error_description = token_data.get("error_description", "GitHub did not return an access token.")
            raise GitHubOAuthLoginError(error_description)
        return GitHubTokenGrant(access_token=access_token, granted_scopes=token_data.get("scope", ""))

    async def fetch_user_profile(self, access_token: str) -> GitHubUserProfile:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        try:
            response = await self._client.get(USER_PROFILE_URL, headers=headers)
        except httpx.HTTPError as error:
            raise GitHubProfileFetchError("Could not reach GitHub to fetch the user profile") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubProfileFetchError(f"GitHub profile request failed: {error.response.text}") from error
        profile_data = response.json()
        return GitHubUserProfile(
            github_id=profile_data["id"],
            github_username=profile_data["login"],
            email=profile_data.get("email"),
            avatar_url=profile_data.get("avatar_url"),
        )

    async def fetch_user_repos(self, access_token: str, page: int) -> list[GitHubRepo]:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        params = {"sort": "updated", "page": page, "per_page": REPOS_PER_PAGE}
        try:
            response = await self._client.get(USER_REPOS_URL, headers=headers, params=params)
        except httpx.HTTPError as error:
            raise GitHubRepoFetchError("Could not reach GitHub to fetch the repo list") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubRepoFetchError(f"GitHub repo list request failed: {error.response.text}") from error
        repos_data = response.json()
        languages_by_repo = await asyncio.gather(
            *(self.fetch_repo_languages(access_token, repo_data["full_name"]) for repo_data in repos_data)
        )
        return [
            self._parse_repo(repo_data, languages)
            for repo_data, languages in zip(repos_data, languages_by_repo, strict=True)
        ]

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        try:
            response = await self._client.get(REPO_URL_TEMPLATE.format(full_name=full_name), headers=headers)
        except httpx.HTTPError as error:
            raise GitHubRepoFetchError("Could not reach GitHub to fetch the repo") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubRepoFetchError(f"GitHub repo request failed: {error.response.text}") from error
        languages = await self.fetch_repo_languages(access_token, full_name)
        return self._parse_repo(response.json(), languages)

    async def fetch_repo_languages(self, access_token: str, full_name: str) -> dict[str, int]:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        url = REPO_LANGUAGES_URL_TEMPLATE.format(full_name=full_name)
        try:
            response = await self._client.get(url, headers=headers)
        except httpx.HTTPError as error:
            raise GitHubRepoFetchError("Could not reach GitHub to fetch repo languages") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubRepoFetchError(f"GitHub languages request failed: {error.response.text}") from error
        return response.json()

    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        url = COMMIT_URL_TEMPLATE.format(full_name=full_name, ref=ref)
        try:
            response = await self._client.get(url, headers=headers, timeout=REPO_INDEXING_REQUEST_TIMEOUT_SECONDS)
        except httpx.HTTPError as error:
            raise GitHubCommitFetchError("Could not reach GitHub to fetch the branch commit") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubCommitFetchError(f"GitHub commit request failed: {error.response.text}") from error
        return response.json()["sha"]

    async def download_tarball(self, access_token: str, full_name: str, ref: str) -> bytes:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        url = TARBALL_URL_TEMPLATE.format(full_name=full_name, ref=ref)
        try:
            response = await self._client.get(
                url, headers=headers, follow_redirects=True, timeout=REPO_INDEXING_REQUEST_TIMEOUT_SECONDS
            )
        except httpx.HTTPError as error:
            raise GitHubTarballFetchError("Could not reach GitHub to download the repo tarball") from error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise GitHubTarballFetchError(f"GitHub tarball request failed: {error.response.text}") from error
        return response.content

    def _parse_repo(self, repo_data: dict, languages: dict[str, int]) -> GitHubRepo:
        python_percentage = _python_percentage(languages)
        return GitHubRepo(
            repo_id=repo_data["id"],
            owner_id=repo_data["owner"]["id"],
            full_name=repo_data["full_name"],
            description=repo_data.get("description"),
            private=repo_data["private"],
            default_branch=repo_data["default_branch"],
            language=repo_data.get("language"),
            python_percentage=round(python_percentage, 1),
            has_enough_python=python_percentage >= PYTHON_PERCENTAGE_THRESHOLD,
        )


def _python_percentage(languages: dict[str, int]) -> float:
    total_bytes = sum(languages.values())
    if total_bytes == 0:
        return 0.0
    return (languages.get("Python", 0) / total_bytes) * 100
