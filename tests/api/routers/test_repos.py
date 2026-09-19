"""
    Tests for the /api/repos router against fakes: no real DB, no real GitHub calls.
"""
from datetime import datetime

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_github_oauth_client,
    get_kafka_producer,
    get_token_cipher,
)
from api.indexing.producer import PublishError
from api.integrations.github import GitHubRepo, GitHubRepoFetchError
from api.routers.repos import router as repos_router
from api.schemas.indexing import RepoRegisteredMessage
from api.security.token_cipher import TokenCipher


class FakeGitHubOAuthClient:
    def __init__(self, *, repo: GitHubRepo | None = None, fetch_error: Exception | None = None) -> None:
        self._repo = repo
        self._fetch_error = fetch_error

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        if self._fetch_error:
            raise self._fetch_error
        return self._repo


class FakeRepoIndexProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[RepoRegisteredMessage] = []

    async def publish(self, topic: str, message: RepoRegisteredMessage, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append(message)


class _ScalarsResult:
    def __init__(self, rows: list[RegisteredRepo | IndexedFile]) -> None:
        self._rows = rows

    def all(self) -> list[RegisteredRepo | IndexedFile]:
        return self._rows


class FakeAsyncSession:
    """Dispatches on the queried entity (RegisteredRepo vs IndexedFile) and, if the statement
    binds a single scalar parameter (as every `where(Model.repo_id == repo_id)` in this router
    does), filters rows by it too -- catching a query that forgets to filter by repo_id at all."""

    def __init__(
        self,
        existing: list[RegisteredRepo] | None = None,
        indexed_files: list[IndexedFile] | None = None,
    ) -> None:
        self._rows: list[RegisteredRepo] = list(existing or [])
        self._indexed_files: list[IndexedFile] = list(indexed_files or [])

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    def _rows_for(self, statement) -> list[RegisteredRepo | IndexedFile]:
        entity = statement.column_descriptions[0]["entity"]
        rows = self._indexed_files if entity is IndexedFile else self._rows
        requested_repo_id = next(iter(statement.compile().params.values()), None)
        if requested_repo_id is None:
            return rows
        return [row for row in rows if row.repo_id == requested_repo_id]

    async def scalar(self, statement) -> RegisteredRepo | IndexedFile | None:
        rows = self._rows_for(statement)
        return rows[0] if rows else None

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult(self._rows_for(statement))

    def add(self, row: RegisteredRepo) -> None:
        self._rows.append(row)

    async def delete(self, row: RegisteredRepo) -> None:
        self._rows.remove(row)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, row: RegisteredRepo) -> None:
        if row.id is None:
            row.id = len(self._rows)
        if row.created_at is None:
            row.created_at = datetime(2026, 1, 1)

    async def get(self, _model, row_id: int) -> RegisteredRepo | None:
        return next((row for row in self._rows if row.id == row_id), None)


def _make_user(cipher: TokenCipher) -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token=cipher.encrypt("gho_token"),
        github_granted_scopes="repo",
    )


def _make_indexed_file(**overrides) -> IndexedFile:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "file_path": "src/module.py",
        "status": IndexedFileStatus.INDEXED,
        "status_reason": None,
        "indexed_at": datetime(2026, 1, 2),
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return IndexedFile(**defaults)


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.INDEXED,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


def _make_github_repo(**overrides) -> GitHubRepo:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "description": None,
        "private": False,
        "default_branch": "main",
        "language": "Python",
        "python_percentage": 90.0,
        "has_enough_python": True,
    }
    defaults.update(overrides)
    return GitHubRepo(**defaults)


def _build_app(
    *,
    github_client,
    session: FakeAsyncSession,
    current_user: User | None = None,
    token_cipher: TokenCipher | None = None,
    kafka_producer: FakeRepoIndexProducer | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(repos_router)

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_github_oauth_client] = lambda: github_client
    app.dependency_overrides[get_token_cipher] = lambda: token_cipher or TokenCipher(
        encryption_key=Fernet.generate_key().decode()
    )
    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_kafka_producer] = lambda: kafka_producer or FakeRepoIndexProducer()
    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user
    return app


def _make_authenticated_user() -> tuple[User, TokenCipher]:
    cipher = TokenCipher(encryption_key=Fernet.generate_key().decode())
    return _make_user(cipher), cipher


def test_register_repo_verifies_against_github_before_persisting() -> None:
    repo = _make_github_repo()
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 201
    assert response.json()["repo_id"] == 10
    assert response.json()["status"] == "pending"


def test_register_repo_rejects_a_repo_id_mismatch() -> None:
    repo = _make_github_repo(repo_id=999)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 400


def test_register_repo_rejects_a_repo_below_the_python_threshold() -> None:
    repo = _make_github_repo(python_percentage=5.0, has_enough_python=False)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 400


def test_register_repo_surfaces_a_github_verification_failure_as_a_bad_gateway() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(fetch_error=GitHubRepoFetchError("boom")),
        session=FakeAsyncSession(),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 502


def test_register_repo_rejects_a_repo_id_already_registered() -> None:
    existing = RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        registered_by_user_id=1,
        status=RepoIndexStatus.INDEXED,
        created_at=datetime(2026, 1, 1),
    )
    repo = _make_github_repo()
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo),
        session=FakeAsyncSession(existing=[existing]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 409


def test_register_repo_allows_re_registering_a_previously_failed_repo() -> None:
    existing = _make_registered_repo(status=RepoIndexStatus.FAILED, status_reason="tarball fetch failed")
    repo = _make_github_repo()
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo),
        session=FakeAsyncSession(existing=[existing]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_list_registered_repos_returns_every_row() -> None:
    existing = RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        registered_by_user_id=1,
        status=RepoIndexStatus.INDEXED,
        created_at=datetime(2026, 1, 1),
    )
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[existing]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos")

    assert response.status_code == 200
    assert [row["repo_id"] for row in response.json()] == [10]


def test_register_repo_publishes_a_repo_registered_message() -> None:
    repo = _make_github_repo()
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo),
        session=FakeAsyncSession(),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    [message] = kafka_producer.published
    assert message.repo_id == 10


def test_register_repo_surfaces_a_kafka_publish_failure_as_a_bad_gateway() -> None:
    repo = _make_github_repo()
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer(publish_error=PublishError("broker unreachable"))
    app = _build_app(
        github_client=FakeGitHubOAuthClient(repo=repo),
        session=FakeAsyncSession(),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    response = client.post("/api/repos", json={"repo_id": 10, "full_name": "octocat/hello-world"})

    assert response.status_code == 502


def test_list_indexed_files_returns_the_repos_files() -> None:
    registered = _make_registered_repo()
    files = [
        _make_indexed_file(id=1, file_path="src/a.py", status=IndexedFileStatus.INDEXED),
        _make_indexed_file(id=2, file_path="src/b.py", status=IndexedFileStatus.FAILED, status_reason="parse error"),
    ]
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=files),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos/10/files")

    assert response.status_code == 200
    assert {row["file_path"] for row in response.json()} == {"src/a.py", "src/b.py"}


def test_list_indexed_files_only_returns_files_for_the_requested_repo() -> None:
    registered = _make_registered_repo()
    files = [
        _make_indexed_file(id=1, repo_id=10, file_path="mine.py"),
        _make_indexed_file(id=2, repo_id=20, file_path="someone-elses.py"),
    ]
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=files),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos/10/files")

    assert response.status_code == 200
    assert [row["file_path"] for row in response.json()] == ["mine.py"]


def test_list_indexed_files_returns_404_for_an_unregistered_repo() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos/999/files")

    assert response.status_code == 404
