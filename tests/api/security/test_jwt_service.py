"""
    Tests for JwtTokenService: pure signing/verification logic, no I/O.
"""
import time
from collections.abc import Callable
from itertools import permutations
from typing import NamedTuple

import jwt
import pytest

from api.security.jwt_service import (
    InvalidAccessTokenError,
    InvalidGuestSessionTokenError,
    InvalidOAuthStateError,
    InvalidUserSessionTokenError,
    JwtTokenService,
)

SECRET_KEY = "test-secret-key-for-jwt-signing-unit-tests"
OTHER_SECRET_KEY = "a-completely-different-secret-for-signing-tests"


class TokenKind(NamedTuple):
    name: str
    issue: Callable[[JwtTokenService], str]
    verify: Callable[[JwtTokenService, str], object]
    error: type[Exception]


ACCESS = TokenKind(
    "access",
    lambda service: service.issue_access_token(user_id=1),
    lambda service, token: service.verify_access_token(token),
    InvalidAccessTokenError,
)
GUEST_SESSION = TokenKind(
    "guest_session",
    lambda service: service.issue_guest_session_token(guest_session_id=1),
    lambda service, token: service.verify_guest_session_token(token),
    InvalidGuestSessionTokenError,
)
USER_SESSION = TokenKind(
    "user_session",
    lambda service: service.issue_user_session_token(user_id=1),
    lambda service, token: service.verify_user_session_token(token),
    InvalidUserSessionTokenError,
)
OAUTH_STATE = TokenKind(
    "oauth_state",
    lambda service: service.issue_oauth_state(),
    lambda service, token: service.verify_oauth_state(token),
    InvalidOAuthStateError,
)

ALL_KINDS = [ACCESS, GUEST_SESSION, USER_SESSION, OAUTH_STATE]
SUBJECT_KINDS = [ACCESS, GUEST_SESSION, USER_SESSION]
CROSS_PURPOSE_PAIRS = list(permutations(ALL_KINDS, 2))


def _kind_id(kind: TokenKind) -> str:
    return kind.name


def _service(
    secret_key: str = SECRET_KEY,
    access_token_ttl_seconds: int = 3600,
    state_token_ttl_seconds: int = 300,
) -> JwtTokenService:
    return JwtTokenService(
        secret_key=secret_key,
        access_token_ttl_seconds=access_token_ttl_seconds,
        state_token_ttl_seconds=state_token_ttl_seconds,
    )


@pytest.fixture
def jwt_service() -> JwtTokenService:
    return _service()


def test_issued_access_token_verifies_to_the_same_user_id(jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_access_token(user_id=42)

    assert jwt_service.verify_access_token(token) == 42


def test_issued_guest_session_token_verifies_to_the_same_guest_session_id(jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_guest_session_token(guest_session_id=7)

    assert jwt_service.verify_guest_session_token(token) == 7


def test_issued_user_session_token_verifies_to_the_same_user_id(jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_user_session_token(user_id=42)

    assert jwt_service.verify_user_session_token(token) == 42


def test_valid_oauth_state_passes_verification(jwt_service: JwtTokenService) -> None:
    state = jwt_service.issue_oauth_state()

    assert jwt_service.verify_oauth_state(state) is None


def test_oauth_state_carries_the_return_to_path_it_was_issued_with(jwt_service: JwtTokenService) -> None:
    state = jwt_service.issue_oauth_state(return_to="/oauth/authorize?client_id=abc")

    assert jwt_service.verify_oauth_state(state) == "/oauth/authorize?client_id=abc"


def test_oauth_state_without_a_return_to_verifies_to_none(jwt_service: JwtTokenService) -> None:
    assert jwt_service.verify_oauth_state(jwt_service.issue_oauth_state()) is None


def test_a_tampered_oauth_state_does_not_yield_its_return_to(jwt_service: JwtTokenService) -> None:
    other_service = _service(secret_key=OTHER_SECRET_KEY)
    forged = other_service.issue_oauth_state(return_to="/oauth/authorize?client_id=evil")

    with pytest.raises(InvalidOAuthStateError):
        jwt_service.verify_oauth_state(forged)


def test_issued_oauth_states_are_unique(jwt_service: JwtTokenService) -> None:
    """Verify two states differ, since a repeated state would defeat CSRF protection."""
    first_state = jwt_service.issue_oauth_state()
    second_state = jwt_service.issue_oauth_state()

    assert first_state != second_state


@pytest.mark.parametrize("kind", ALL_KINDS, ids=_kind_id)
def test_expired_token_is_rejected(kind: TokenKind) -> None:
    service = _service(access_token_ttl_seconds=-1, state_token_ttl_seconds=-1)
    token = kind.issue(service)

    with pytest.raises(kind.error):
        kind.verify(service, token)


@pytest.mark.parametrize("kind", ALL_KINDS, ids=_kind_id)
def test_token_signed_with_a_different_key_is_rejected(kind: TokenKind, jwt_service: JwtTokenService) -> None:
    token = kind.issue(_service(secret_key=OTHER_SECRET_KEY))

    with pytest.raises(kind.error):
        kind.verify(jwt_service, token)


@pytest.mark.parametrize("kind", ALL_KINDS, ids=_kind_id)
def test_malformed_token_is_rejected(kind: TokenKind, jwt_service: JwtTokenService) -> None:
    with pytest.raises(kind.error):
        kind.verify(jwt_service, "not-a-real-jwt")


@pytest.mark.parametrize("kind", ALL_KINDS, ids=_kind_id)
def test_empty_token_is_rejected(kind: TokenKind, jwt_service: JwtTokenService) -> None:
    with pytest.raises(kind.error):
        kind.verify(jwt_service, "")


@pytest.mark.parametrize(
    "issued_as, verified_as",
    CROSS_PURPOSE_PAIRS,
    ids=lambda kind: kind.name,
)
def test_token_is_rejected_when_verified_as_another_kind(
    issued_as: TokenKind,
    verified_as: TokenKind,
    jwt_service: JwtTokenService,
) -> None:
    """Verify every token kind is only accepted by its own verifier.

    A bearer token, a session cookie and an OAuth state must never be
    interchangeable, or one leaked credential unlocks another surface.
    """
    token = issued_as.issue(jwt_service)

    with pytest.raises(verified_as.error):
        verified_as.verify(jwt_service, token)


@pytest.mark.parametrize("subject", ["not-a-number", "", None], ids=["text", "empty", "null"])
@pytest.mark.parametrize("kind", SUBJECT_KINDS, ids=_kind_id)
def test_validly_signed_token_with_a_non_numeric_subject_is_rejected(
    kind: TokenKind, subject: str | None, jwt_service: JwtTokenService
) -> None:
    token = jwt.encode({"sub": subject, "purpose": kind.name, "exp": int(time.time()) + 60}, SECRET_KEY, "HS256")

    with pytest.raises(kind.error):
        kind.verify(jwt_service, token)


def test_validly_signed_token_without_a_subject_is_rejected(jwt_service: JwtTokenService) -> None:
    token = jwt.encode({"purpose": USER_SESSION.name, "exp": int(time.time()) + 60}, SECRET_KEY, "HS256")

    with pytest.raises(InvalidUserSessionTokenError):
        jwt_service.verify_user_session_token(token)


@pytest.mark.parametrize("kind", SUBJECT_KINDS, ids=_kind_id)
def test_subject_token_lifetime_follows_the_access_ttl(kind: TokenKind) -> None:
    """Verify a session-like token is not cut short by the OAuth state TTL."""
    service = _service(access_token_ttl_seconds=3600, state_token_ttl_seconds=-1)
    token = kind.issue(service)

    assert kind.verify(service, token) == 1


def test_oauth_state_lifetime_follows_the_state_ttl() -> None:
    """Verify an OAuth state is not cut short by the access TTL."""
    service = _service(access_token_ttl_seconds=-1, state_token_ttl_seconds=300)
    state = service.issue_oauth_state()

    assert service.verify_oauth_state(state) is None
