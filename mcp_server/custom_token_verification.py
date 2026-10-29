"""
    Logic that will verify that the token will received from the 
    3rd party provider is Ok and save to AccessToken. (used in get_acces_token)
"""
from http import HTTPStatus

import httpx
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel

CURRENT_USER_PATH = "/api/oauth/github/me"
API_CLIENT_ID = "api"


class TokenVerificationUnavailable(Exception):
    """Raised when api/ cannot say whether a token is valid, as opposed to saying it is not."""


class CurrentUser(BaseModel):
    id: int


class ApiTokenVerifier:
    """Asks api/ whether a bearer token identifies a user; api/ stays the only place that decides."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def verify_token(self, token: str) -> AccessToken | None:
        """Returns the token's AccessToken, or None when api/ rejects it.

        Raises TokenVerificationUnavailable when api/ is unreachable or answers anything but 200 or 401.
        """
        response = await self._get_current_user(token)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            return None
        if response.status_code != HTTPStatus.OK:
            raise TokenVerificationUnavailable(f"api/ answered {response.status_code} while verifying a token.")
        user = CurrentUser.model_validate_json(response.content)
        return AccessToken(token=token, client_id=API_CLIENT_ID, scopes=[], subject=str(user.id))

    async def _get_current_user(self, token: str) -> httpx.Response:
        try:
            return await self._client.get(CURRENT_USER_PATH, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as error:
            raise TokenVerificationUnavailable("api/ is unreachable while verifying a token.") from error
