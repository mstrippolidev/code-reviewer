import time
import uuid

import jwt

ACCESS_TOKEN_PURPOSE = "access"
OAUTH_STATE_PURPOSE = "oauth_state"
GUEST_SESSION_PURPOSE = "guest_session"
USER_SESSION_PURPOSE = "user_session"


class InvalidAccessTokenError(Exception):
    """Raised when a bearer token fails signature, expiry, or purpose verification."""


class InvalidGuestSessionTokenError(Exception):
    """Raised when a guest session cookie fails signature, expiry, or purpose verification."""


class InvalidOAuthStateError(Exception):
    """Raised when an OAuth 'state' value fails signature, expiry, or purpose verification."""


class InvalidUserSessionTokenError(Exception):
    """Raised when a user session cookie fails signature, expiry, or purpose verification."""


class JwtTokenService:
    """Issues and verifies HS256 JWTs for session access tokens, user and guest session cookies, and OAuth CSRF state values."""

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
        return self._decode_subject_id(token, expected_purpose=ACCESS_TOKEN_PURPOSE, error=InvalidAccessTokenError)

    def issue_guest_session_token(self, *, guest_session_id: int) -> str:
        return self._encode(
            subject=str(guest_session_id),
            purpose=GUEST_SESSION_PURPOSE,
            ttl_seconds=self._access_token_ttl_seconds,
        )

    def verify_guest_session_token(self, token: str) -> int:
        """Returns the guest session id embedded in the token.

        Raises:
            InvalidGuestSessionTokenError: If the token is malformed, expired, or not a guest session token.
        """
        return self._decode_subject_id(
            token, expected_purpose=GUEST_SESSION_PURPOSE, error=InvalidGuestSessionTokenError
        )

    def issue_user_session_token(self, *, user_id: int) -> str:
        return self._encode(
            subject=str(user_id),
            purpose=USER_SESSION_PURPOSE,
            ttl_seconds=self._access_token_ttl_seconds,
        )

    def verify_user_session_token(self, token: str) -> int:
        """Returns the user id embedded in the token.

        Raises:
            InvalidUserSessionTokenError: If the token is malformed, expired, or not a user session token.
        """
        return self._decode_subject_id(token, expected_purpose=USER_SESSION_PURPOSE, error=InvalidUserSessionTokenError)

    def issue_oauth_state(self, return_to: str | None = None) -> str:
        payload = self._base_payload(
            subject=str(uuid.uuid4()),
            purpose=OAUTH_STATE_PURPOSE,
            ttl_seconds=self._state_token_ttl_seconds,
        )
        if return_to is not None:
            payload["return_to"] = return_to
        return self._sign(payload)

    def verify_oauth_state(self, state: str) -> str | None:
        """Returns the return_to path the state was issued with, if any.

        Raises:
            InvalidOAuthStateError: If the state is malformed, expired, or not an OAuth state token.
        """
        payload = self._decode(state, expected_purpose=OAUTH_STATE_PURPOSE, error=InvalidOAuthStateError)
        return payload.get("return_to")

    def _encode(self, *, subject: str, purpose: str, ttl_seconds: int) -> str:
        return self._sign(self._base_payload(subject=subject, purpose=purpose, ttl_seconds=ttl_seconds))

    def _base_payload(self, *, subject: str, purpose: str, ttl_seconds: int) -> dict:
        issued_at = int(time.time())
        return {
            "sub": subject,
            "purpose": purpose,
            "iat": issued_at,
            "exp": issued_at + ttl_seconds,
        }

    def _sign(self, payload: dict) -> str:
        return jwt.encode(payload, self._secret_key, algorithm=self._ALGORITHM)

    def _decode_subject_id(self, token: str, *, expected_purpose: str, error: type[Exception]) -> int:
        payload = self._decode(token, expected_purpose=expected_purpose, error=error)
        try:
            return int(payload["sub"])
        except (KeyError, TypeError, ValueError) as subject_error:
            raise error("Token subject is not a valid id") from subject_error

    def _decode(self, token: str, *, expected_purpose: str, error: type[Exception]) -> dict:
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._ALGORITHM])
        except jwt.PyJWTError as decode_error:
            raise error("Token failed signature or expiry verification") from decode_error
        if payload.get("purpose") != expected_purpose:
            raise error("Token was issued for a different purpose")
        return payload
