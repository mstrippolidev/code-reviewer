"""
    Custom caller for Authentication.

    This custom caller could be wire up directly to httpx and
    set up the auth
"""
from collections.abc import Generator

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token


class MissingCallerTokenError(Exception):
    """Raised when a call to api/ is attempted outside an authenticated MCP request."""


class CallerBearerAuth(httpx.Auth):
    """Sends the calling MCP client's own bearer token on every 
    request to api/."""

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        """
            Public method to be inhered
        """
        access_token = get_access_token() # get the current access token for this client
        if access_token is None:
            raise MissingCallerTokenError("No authenticated caller; refusing to call api/ anonymously.")
        request.headers["Authorization"] = f"Bearer {access_token.token}"
        yield request
