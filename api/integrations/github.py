"""
    GitHub OAuth login integration: authorization URL, code exchange, and profile fetch.
"""
import urllib.parse
from dataclasses import dataclass

import httpx

from api.schemas.github import GitHubUserProfile


AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_PROFILE_URL = "https://api.github.com/user"
OAUTH_SCOPE = "repo read:user"


class GitHubOAuthLoginError(Exception):
    """Raised when GitHub rejects a code exchange or refuses to return an access token."""


class GitHubProfileFetchError(Exception):
    """Raised when the authenticated user's GitHub profile cannot be retrieved."""


@dataclass(frozen=True)
class GitHubOAuthConfig:
    """Configuration for GitHub OAuth integration."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": OAUTH_SCOPE,
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

    def build_authorize_url(self, *, state: str) -> str:
        return self._config.get_authorization_url(state)

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
