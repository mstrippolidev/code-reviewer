"""
    Tests for get_current_user accepting a bearer token or the user session cookie.

    Tokens are really signed and verified; only the DB session is faked.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.db.models.user import User
from api.dependencies import USER_SESSION_COOKIE, get_current_user, get_db_session, get_jwt_service
from api.security.jwt_service import JwtTokenService

USER_ID = 3
OTHER_USER_ID = 4

JWT_SERVICE = JwtTokenService(
    secret_key="session-auth-test-secret-key-32-bytes", access_token_ttl_seconds=3600, state_token_ttl_seconds=300
)


class FakeSession:
    def __init__(self, users: dict[int, User]) -> None:
        self._users = users

    async def get(self, _model, user_id: int) -> User | None:
        return self._users.get(user_id)


def _user(user_id: int) -> User:
    return User(id=user_id, github_id=user_id, github_username=f"user{user_id}", encrypted_github_token="x")


def _client(users: dict[int, User] | None = None) -> TestClient:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)) -> dict[str, int]:
        return {"user_id": user.id}

    async def _fake_session():
        yield FakeSession(users if users is not None else {USER_ID: _user(USER_ID), OTHER_USER_ID: _user(OTHER_USER_ID)})

    app.dependency_overrides[get_db_session] = _fake_session
    app.dependency_overrides[get_jwt_service] = lambda: JWT_SERVICE
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_the_session_cookie_authenticates_the_user() -> None:
    cookies = {USER_SESSION_COOKIE: JWT_SERVICE.issue_user_session_token(user_id=USER_ID)}

    response = _client().get("/whoami", cookies=cookies)

    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID}


def test_the_bearer_token_authenticates_the_user() -> None:
    headers = _bearer(JWT_SERVICE.issue_access_token(user_id=USER_ID))

    response = _client().get("/whoami", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID}


def test_a_request_with_neither_credential_is_unauthorized() -> None:
    assert _client().get("/whoami").status_code == 401


def test_an_access_token_in_the_cookie_is_rejected() -> None:
    cookies = {USER_SESSION_COOKIE: JWT_SERVICE.issue_access_token(user_id=USER_ID)}

    assert _client().get("/whoami", cookies=cookies).status_code == 401


def test_a_session_token_as_a_bearer_is_rejected() -> None:
    headers = _bearer(JWT_SERVICE.issue_user_session_token(user_id=USER_ID))

    assert _client().get("/whoami", headers=headers).status_code == 401


def test_a_garbage_cookie_is_unauthorized() -> None:
    assert _client().get("/whoami", cookies={USER_SESSION_COOKIE: "garbage"}).status_code == 401


def test_a_valid_cookie_for_a_deleted_user_is_unauthorized() -> None:
    cookies = {USER_SESSION_COOKIE: JWT_SERVICE.issue_user_session_token(user_id=USER_ID)}

    assert _client(users={}).get("/whoami", cookies=cookies).status_code == 401


def test_an_explicit_bearer_wins_over_the_cookie() -> None:
    headers = _bearer(JWT_SERVICE.issue_access_token(user_id=OTHER_USER_ID))
    cookies = {USER_SESSION_COOKIE: JWT_SERVICE.issue_user_session_token(user_id=USER_ID)}

    response = _client().get("/whoami", headers=headers, cookies=cookies)

    assert response.json() == {"user_id": OTHER_USER_ID}


def test_a_bad_bearer_falls_back_to_a_valid_cookie() -> None:
    cookies = {USER_SESSION_COOKIE: JWT_SERVICE.issue_user_session_token(user_id=USER_ID)}

    response = _client().get("/whoami", headers=_bearer("garbage"), cookies=cookies)

    assert response.json() == {"user_id": USER_ID}


@pytest.mark.parametrize("header", ["Basic abc", "Bearer"], ids=["wrong-scheme", "no-token"])
def test_a_malformed_authorization_header_is_unauthorized(header: str) -> None:
    assert _client().get("/whoami", headers={"Authorization": header}).status_code == 401
