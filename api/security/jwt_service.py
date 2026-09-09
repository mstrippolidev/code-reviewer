import time
import uuid

import jwt

ACCESS_TOKEN_PURPOSE = "access"
OAUTH_STATE_PURPOSE = "oauth_state"


class InvalidAccessTokenError(Exception):
    """Raised when a bearer token fails signature, expiry, or purpose verification."""


class InvalidOAuthStateError(Exception):
    """Raised when an OAuth 'state' value fails signature, expiry, or purpose verification."""


class JwtTokenService:
    """Issues and verifies HS256 JWTs for session access tokens and OAuth CSRF state values."""

    _ALGORITHM = "HS256"

    def __init__(
        self,
        secret_key: str,
        access_token_ttl_seconds: int,
        state_token_ttl_seconds: int,
    ) -> None:
        self._secret_key = secret_key
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._state_token_ttl_seconds = state_token_ttl_seconds

    def issue_access_token(self, *, user_id: int) -> str:
        return self._encode(
            subject=str(user_id),
            purpose=ACCESS_TOKEN_PURPOSE,
            ttl_seconds=self._access_token_ttl_seconds,
        )

    def verify_access_token(self, token: str) -> int:
        """Returns the user id embedded in the token.

        Raises:
            InvalidAccessTokenError: If the token is malformed, expired, or not an access token.
        """
        payload = self._decode(token, expected_purpose=ACCESS_TOKEN_PURPOSE, error=InvalidAccessTokenError)
        return int(payload["sub"])

    def issue_oauth_state(self) -> str:
        return self._encode(
            subject=str(uuid.uuid4()),
            purpose=OAUTH_STATE_PURPOSE,
            ttl_seconds=self._state_token_ttl_seconds,
        )

    def verify_oauth_state(self, state: str) -> None:
        """Raises InvalidOAuthStateError if the state is malformed, expired, or not an OAuth state token."""
        self._decode(state, expected_purpose=OAUTH_STATE_PURPOSE, error=InvalidOAuthStateError)

    def _encode(self, *, subject: str, purpose: str, ttl_seconds: int) -> str:
        issued_at = int(time.time())
        payload = {
            "sub": subject,
            "purpose": purpose,
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
        }
        return jwt.encode(payload, self._secret_key, algorithm=self._ALGORITHM)

    def _decode(self, token: str, *, expected_purpose: str, error: type[Exception]) -> dict:
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._ALGORITHM])
        except jwt.PyJWTError as decode_error:
            raise error("Token failed signature or expiry verification") from decode_error
        if payload.get("purpose") != expected_purpose:
            raise error("Token was issued for a different purpose")
        return payload
