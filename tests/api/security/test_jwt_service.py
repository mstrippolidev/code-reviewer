"""
    Tests for JwtTokenService: pure signing/verification logic, no I/O.
"""
import pytest

from api.security.jwt_service import (
    InvalidAccessTokenError,
    InvalidOAuthStateError,
    JwtTokenService,
)

SECRET_KEY = "test-secret-key-for-jwt-signing-unit-tests"


@pytest.fixture
def jwt_service() -> JwtTokenService:
    return JwtTokenService(secret_key=SECRET_KEY, access_token_ttl_seconds=3600, state_token_ttl_seconds=300)


def test_issued_access_token_verifies_to_the_same_user_id(jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_access_token(user_id=42)

    assert jwt_service.verify_access_token(token) == 42


def test_expired_access_token_is_rejected() -> None:
    service = JwtTokenService(secret_key=SECRET_KEY, access_token_ttl_seconds=-1, state_token_ttl_seconds=300)
    token = service.issue_access_token(user_id=1)

    with pytest.raises(InvalidAccessTokenError):
        service.verify_access_token(token)


def test_access_token_signed_with_a_different_key_is_rejected(jwt_service: JwtTokenService) -> None:
    other_service = JwtTokenService(
        secret_key="a-completely-different-secret",
        access_token_ttl_seconds=3600,
        state_token_ttl_seconds=300,
    )
    token = other_service.issue_access_token(user_id=1)

    with pytest.raises(InvalidAccessTokenError):
        jwt_service.verify_access_token(token)


def test_malformed_token_is_rejected(jwt_service: JwtTokenService) -> None:
    with pytest.raises(InvalidAccessTokenError):
        jwt_service.verify_access_token("not-a-real-jwt")


def test_oauth_state_token_cannot_be_used_as_an_access_token(jwt_service: JwtTokenService) -> None:
    state = jwt_service.issue_oauth_state()

    with pytest.raises(InvalidAccessTokenError):
        jwt_service.verify_access_token(state)


def test_access_token_cannot_be_used_as_oauth_state(jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_access_token(user_id=1)

    with pytest.raises(InvalidOAuthStateError):
        jwt_service.verify_oauth_state(token)


def test_valid_oauth_state_passes_verification(jwt_service: JwtTokenService) -> None:
    state = jwt_service.issue_oauth_state()

    jwt_service.verify_oauth_state(state)


def test_expired_oauth_state_is_rejected() -> None:
    service = JwtTokenService(secret_key=SECRET_KEY, access_token_ttl_seconds=3600, state_token_ttl_seconds=-1)
    state = service.issue_oauth_state()

    with pytest.raises(InvalidOAuthStateError):
        service.verify_oauth_state(state)
