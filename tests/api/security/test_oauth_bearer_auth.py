"""
    Tests for who the API takes the caller to be when a request carries an OAuth access token.

    Tokens and cookies are really signed or issued and verified; only the DB session and token rows are in memory.
"""
import asyncio

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.db.models.user import User
from api.dependencies import (
    USER_SESSION_COOKIE,
    UserIdResolver,
    get_current_user,
    get_db_session,
    get_jwt_service,
    get_user_id_resolver,
)
from api.oauth.access_token_verifier import OAuthAccessTokenVerifier
from api.oauth.dependencies import require_session_user_id
from api.oauth.token_service import OAuthTokenService, TokenLifetimes
from api.security.jwt_service import JwtTokenService
from tests.api.oauth.fakes import FakeClock, FakeTokenRepository

USER_ID = 3
OTHER_USER_ID = 4
CLIENT_ID = "client-a"
ACCESS_SECONDS = 3600

JWT_SERVICE = JwtTokenService(
    secret_key="oauth-bearer-test-secret-key-32-bytes", access_token_ttl_seconds=3600, state_token_ttl_seconds=300
)
LIFETIMES = TokenLifetimes(
    access_seconds=ACCESS_SECONDS,
    refresh_idle_seconds=7 * 24 * 3600,
    refresh_absolute_seconds=30 * 24 * 3600,
)


class FakeSession:
    def __init__(self, user_ids: set[int]) -> None:
        self._user_ids = user_ids

    async def get(self, _model, user_id: int) -> User | None:
        return _user(user_id) if user_id in self._user_ids else None


def _user(user_id: int) -> User:
    return User(id=user_id, github_id=user_id, github_username=f"user{user_id}", encrypted_github_token="x")


class OAuthWorld:
    """The app under test plus the token store and clock behind its OAuth verifier."""

    def __init__(self, existing_user_ids: set[int] | None = None) -> None:
        self.clock = FakeClock()
        self.repository = FakeTokenRepository()
        self.service = OAuthTokenService(self.repository, LIFETIMES, self.clock)
        self.app = self._build_app(existing_user_ids if existing_user_ids is not None else {USER_ID, OTHER_USER_ID})
        self.client = TestClient(self.app)

    def issue_access_token(self, user_id: int = USER_ID) -> str:
        return asyncio.run(self.service.issue(user_id, CLIENT_ID)).access_token

    def revoke(self, access_token: str) -> None:
        asyncio.run(self.service.revoke(access_token))

    def _build_app(self, existing_user_ids: set[int]) -> FastAPI:
        app = FastAPI()

        @app.get("/whoami")
        async def whoami(user: User = Depends(get_current_user)) -> dict[str, int]:
            return {"user_id": user.id}

        @app.get("/session-only")
        def session_only(user_id: int = Depends(require_session_user_id)) -> dict[str, int]:
            return {"user_id": user_id}

        async def _fake_session():
            yield FakeSession(existing_user_ids)

        app.dependency_overrides[get_db_session] = _fake_session
        app.dependency_overrides[get_jwt_service] = lambda: JWT_SERVICE
        app.dependency_overrides[get_user_id_resolver] = lambda: UserIdResolver(
            JWT_SERVICE, OAuthAccessTokenVerifier(self.repository, self.clock)
        )
        return app


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _session_cookie(user_id: int) -> dict[str, str]:
    return {USER_SESSION_COOKIE: JWT_SERVICE.issue_user_session_token(user_id=user_id)}


def test_an_oauth_access_token_authenticates_the_user() -> None:
    world = OAuthWorld()

    response = world.client.get("/whoami", headers=_bearer(world.issue_access_token(USER_ID)))

    assert response.status_code == 200
    assert response.json() == {"user_id": USER_ID}


def test_a_login_jwt_still_authenticates_the_user() -> None:
    world = OAuthWorld()

    response = world.client.get("/whoami", headers=_bearer(JWT_SERVICE.issue_access_token(user_id=USER_ID)))

    assert response.json() == {"user_id": USER_ID}


def test_an_oauth_access_token_wins_over_the_cookie() -> None:
    world = OAuthWorld()
    headers = _bearer(world.issue_access_token(OTHER_USER_ID))

    response = world.client.get("/whoami", headers=headers, cookies=_session_cookie(USER_ID))

    assert response.json() == {"user_id": OTHER_USER_ID}


def test_an_expired_oauth_access_token_is_unauthorized() -> None:
    world = OAuthWorld()
    headers = _bearer(world.issue_access_token())
    world.clock.advance(seconds=ACCESS_SECONDS)

    assert world.client.get("/whoami", headers=headers).status_code == 401


def test_a_revoked_oauth_access_token_is_unauthorized() -> None:
    world = OAuthWorld()
    token = world.issue_access_token()
    world.revoke(token)

    assert world.client.get("/whoami", headers=_bearer(token)).status_code == 401


def test_a_rejected_oauth_access_token_falls_back_to_a_valid_cookie() -> None:
    world = OAuthWorld()
    token = world.issue_access_token(OTHER_USER_ID)
    world.revoke(token)

    response = world.client.get("/whoami", headers=_bearer(token), cookies=_session_cookie(USER_ID))

    assert response.json() == {"user_id": USER_ID}


def test_an_oauth_access_token_for_a_deleted_user_is_unauthorized() -> None:
    world = OAuthWorld(existing_user_ids=set())

    response = world.client.get("/whoami", headers=_bearer(world.issue_access_token()))

    assert response.status_code == 401


def test_an_oauth_access_token_cannot_reach_a_cookie_only_route() -> None:
    world = OAuthWorld()

    response = world.client.get("/session-only", headers=_bearer(world.issue_access_token()))

    assert response.status_code == 401


def test_the_cookie_still_reaches_a_cookie_only_route() -> None:
    world = OAuthWorld()

    response = world.client.get("/session-only", cookies=_session_cookie(USER_ID))

    assert response.json() == {"user_id": USER_ID}
