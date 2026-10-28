class InvalidGrantError(Exception):
    """Raised when an authorization code or refresh token cannot be redeemed.

    Callers answer the same `invalid_grant` whatever the cause; the message is for logs only.
    """


class UnknownClientError(Exception):
    """Raised when a client_id is not registered."""


class InvalidRedirectUriError(Exception):
    """Raised when a redirect URI is not one a client may register."""


class InvalidReturnToError(Exception):
    """Raised when a post-login return path is not an OAuth authorize request on this server."""


class OAuthProtocolError(Exception):
    """An error answered directly to the caller as {"error": ..., "error_description": ...}."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


class AuthorizationRedirectError(Exception):
    """An authorization request error that is answered by redirecting back to the client's redirect URI."""

    def __init__(self, redirect_uri: str, error: str, description: str, state: str | None) -> None:
        super().__init__(description)
        self.redirect_uri = redirect_uri
        self.error = error
        self.description = description
        self.state = state
