"""
    Tests for the /api/oauth/github router against fakes: no real DB, no real GitHub calls.
"""
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_frontend_base_url,
    get_github_oauth_client,
    get_jwt_service,
    get_token_cipher,
)
from api.integrations.github import GitHubOAuthLoginError, GitHubRepoFetchError, GitHubTokenGrant
from api.routers.auth import router as auth_router
from api.schemas.github import GitHubRepo, GitHubUserProfile
from api.security.jwt_service import JwtTokenService
from api.security.token_cipher import TokenCipher

SECRET_KEY = "test-secret-key-for-router-tests"
FRONTEND_BASE_URL = "http://localhost:5173"


class FakeGitHubOAuthClient:
    """Stands in for GitHubOAuthClient; each method returns a canned result or raises a canned error."""

    def __init__(
        self,
        *,
        token_grant: GitHubTokenGrant | None = None,
        profile: GitHubUserProfile | None = None,
        repos: list[GitHubRepo] | None = None,
        exchange_error: Exception | None = None,
        repos_error: Exception | None = None,
    ) -> None:
        self._token_grant = token_grant
        self._profile = profile
        self._repos = repos or []
        self._exchange_error = exchange_error
        self._repos_error = repos_error
        self.requested_page: int | None = None

    def build_authorize_url(self, *, state: str, access_level) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}&access_level={access_level.value}"

    async def exchange_code_for_token(self, code: str) -> GitHubTokenGrant:
        if self._exchange_error:
            raise self._exchange_error
        return self._token_grant

    async def fetch_user_profile(self, access_token: str) -> GitHubUserProfile:
        return self._profile

    async def fetch_user_repos(self, access_token: str, page: int) -> list[GitHubRepo]:
        if self._repos_error:
            raise self._repos_error
        self.requested_page = page
        return self._repos


class FakeAsyncSession:
    """Stands in for AsyncSession, covering only the upsert calls _create_or_update_user_from_github_login makes."""

    def __init__(self, existing_user: User | None = None) -> None:
        self.existing_user = existing_user
        self.added: list[User] = []

    async def scalar(self, _statement):
        return self.existing_user

    def add(self, user: User) -> None:
        self.added.append(user)

    async def commit(self) -> None:
        pass

    async def refresh(self, user: User) -> None:
        if user.id is None:
            user.id = 1


def _build_app(*, github_client, session: FakeAsyncSession | None = None, current_user: User | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router)

    async def _fake_db_session():
        yield session or FakeAsyncSession()

    app.dependency_overrides[get_github_oauth_client] = lambda: github_client
    app.dependency_overrides[get_jwt_service] = lambda: JwtTokenService(
        secret_key=SECRET_KEY, access_token_ttl_seconds=3600, state_token_ttl_seconds=300
    )
    app.dependency_overrides[get_token_cipher] = lambda: TokenCipher(encryption_key=Fernet.generate_key().decode())
    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_frontend_base_url] = lambda: FRONTEND_BASE_URL
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _make_user(*, encrypted_github_token: str = "irrelevant") -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token=encrypted_github_token,
        github_granted_scopes="repo,read:user",
    )


def test_login_redirects_to_the_github_authorize_url() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient())
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/login")

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize")


def test_callback_rejects_a_denied_login() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient())
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/callback", params={"error": "access_denied"})

    assert response.status_code == 400


def test_callback_rejects_a_missing_code_or_state() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient())
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/callback")

    assert response.status_code == 400


def test_callback_rejects_an_invalid_state() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient())
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/callback", params={"code": "abc", "state": "not-a-real-state"})

    assert response.status_code == 400


def test_callback_redirects_to_the_frontend_with_an_access_token() -> None:
    jwt_service = JwtTokenService(secret_key=SECRET_KEY, access_token_ttl_seconds=3600, state_token_ttl_seconds=300)
    fake_client = FakeGitHubOAuthClient(
        token_grant=GitHubTokenGrant(access_token="gho_token", granted_scopes="repo,read:user"),
        profile=GitHubUserProfile(github_id=1, github_username="octocat", email=None, avatar_url=None),
    )
    app = _build_app(github_client=fake_client)
    app.dependency_overrides[get_jwt_service] = lambda: jwt_service
    state = jwt_service.issue_oauth_state()
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/callback", params={"code": "abc", "state": state})

    assert response.status_code == 307
    assert response.headers["location"].startswith(f"{FRONTEND_BASE_URL}/callback?token=")


def test_callback_surfaces_a_github_token_exchange_failure_as_a_bad_gateway() -> None:
    jwt_service = JwtTokenService(secret_key=SECRET_KEY, access_token_ttl_seconds=3600, state_token_ttl_seconds=300)
    fake_client = FakeGitHubOAuthClient(exchange_error=GitHubOAuthLoginError("bad code"))
    app = _build_app(github_client=fake_client)
    app.dependency_overrides[get_jwt_service] = lambda: jwt_service
    state = jwt_service.issue_oauth_state()
    client = TestClient(app, follow_redirects=False)

    response = client.get("/api/oauth/github/callback", params={"code": "abc", "state": state})

    assert response.status_code == 502


def test_me_returns_the_current_user() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient(), current_user=_make_user())
    client = TestClient(app)

    response = client.get("/api/oauth/github/me")

    assert response.status_code == 200
    assert response.json()["github_username"] == "octocat"


def test_repos_returns_the_authenticated_users_repo_list() -> None:
    encryption_key = Fernet.generate_key().decode()
    cipher = TokenCipher(encryption_key=encryption_key)
    user = _make_user(encrypted_github_token=cipher.encrypt("gho_token"))
    repo = GitHubRepo(
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        description=None,
        private=False,
        default_branch="main",
        language="Python",
        python_percentage=100.0,
        has_enough_python=True,
    )
    fake_client = FakeGitHubOAuthClient(repos=[repo])
    app = _build_app(github_client=fake_client, current_user=user)
    app.dependency_overrides[get_token_cipher] = lambda: cipher
    client = TestClient(app)

    response = client.get("/api/oauth/github/repos", params={"page": 2})

    assert response.status_code == 200
    assert response.json() == [repo.model_dump()]
    assert fake_client.requested_page == 2


def test_repos_rejects_a_page_number_below_one() -> None:
    app = _build_app(github_client=FakeGitHubOAuthClient(), current_user=_make_user())
    client = TestClient(app)

    response = client.get("/api/oauth/github/repos", params={"page": 0})

    assert response.status_code == 422


def test_repos_surfaces_a_github_fetch_failure_as_a_bad_gateway() -> None:
    encryption_key = Fernet.generate_key().decode()
    cipher = TokenCipher(encryption_key=encryption_key)
    user = _make_user(encrypted_github_token=cipher.encrypt("gho_token"))
    fake_client = FakeGitHubOAuthClient(repos_error=GitHubRepoFetchError("boom"))
    app = _build_app(github_client=fake_client, current_user=user)
    app.dependency_overrides[get_token_cipher] = lambda: cipher
    client = TestClient(app)

    response = client.get("/api/oauth/github/repos")

    assert response.status_code == 502
