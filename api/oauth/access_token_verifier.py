from collections.abc import Callable
from datetime import datetime

from api.oauth.errors import InvalidOAuthAccessTokenError
from api.oauth.token_repository import OAuthTokenRepository
from api.oauth.token_secrets import hash_secret
from api.oauth.token_service import utc_now


class OAuthAccessTokenVerifier:
    """Resolves an opaque OAuth access token to the user it was issued to; read-only, never commits."""

    def __init__(self, repository: OAuthTokenRepository, clock: Callable[[], datetime] = utc_now) -> None:
        self._repository = repository
        self._clock = clock

    async def verify(self, access_token: str) -> int:
        """Returns the token's user id.

        Raises InvalidOAuthAccessTokenError when the token is unknown, its family is revoked or it has expired.
        A refresh token is not an access token and is rejected as unknown.
        """
        row = await self._repository.find_by_access_hash(hash_secret(access_token))
        if row is None:
            raise InvalidOAuthAccessTokenError("unknown access token")
        if row.revoked_at is not None:
            raise InvalidOAuthAccessTokenError("access token is revoked")
        if self._clock() >= row.access_expires_at:
            raise InvalidOAuthAccessTokenError("access token expired")
        return row.user_id
