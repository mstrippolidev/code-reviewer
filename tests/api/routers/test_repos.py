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
    get_rag_manager,
    get_token_cipher,
)
from api.indexing.producer import PublishError
from api.integrations.github import GitHubCommitFetchError, GitHubRepo, GitHubRepoFetchError
from api.routers.repos import router as repos_router
from api.schemas.indexing import RepoRegisteredMessage
from api.schemas.repos import RepoStatusProgressMessage
from api.security.token_cipher import TokenCipher
from code_reviewer.rag.errors import VectorStoreDeletionError


class FakeGitHubOAuthClient:
    def __init__(
        self,
        *,
        repo: GitHubRepo | None = None,
        fetch_error: Exception | None = None,
        commit_sha: str | None = "def456",
        commit_fetch_error: Exception | None = None,
    ) -> None:
        self._repo = repo
        self._fetch_error = fetch_error
        self._commit_sha = commit_sha
        self._commit_fetch_error = commit_fetch_error

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        if self._fetch_error:
            raise self._fetch_error
        return self._repo

    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str:
        if self._commit_fetch_error:
            raise self._commit_fetch_error
        return self._commit_sha


class FakeRepoIndexProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[RepoRegisteredMessage | RepoStatusProgressMessage] = []

    async def publish(self, topic: str, message: RepoRegisteredMessage | RepoStatusProgressMessage, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append(message)


class FakeRagManager:
    def __init__(self, *, delete_error: Exception | None = None) -> None:
        self._delete_error = delete_error
        self.deleted_repo_ids: list[str] = []

    def delete_repo(self, repo_id: str) -> None:
        if self._delete_error:
            raise self._delete_error
        self.deleted_repo_ids.append(repo_id)


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

    async def execute(self, statement) -> None:
        requested_repo_id = next(iter(statement.compile().params.values()), None)
        self._indexed_files = [row for row in self._indexed_files if row.repo_id != requested_repo_id]

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
        "branch": "main",
        "commit_sha": None,
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.COMPLETED,
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
    rag_manager: FakeRagManager | None = None,
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
    app.dependency_overrides[get_rag_manager] = lambda: rag_manager or FakeRagManager()
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
        branch="main",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
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
        branch="main",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
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


def test_get_indexed_file_content_returns_the_stored_source() -> None:
    registered = _make_registered_repo()
    stored = _make_indexed_file(file_path="src/a.py", content="def add(a, b):\n    return a + b\n")
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[stored]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos/10/files/content", params={"file_path": "src/a.py"})

    assert response.status_code == 200
    assert response.json() == {"file_path": "src/a.py", "content": "def add(a, b):\n    return a + b\n"}


def test_get_indexed_file_content_returns_404_when_the_file_has_no_indexed_content() -> None:
    registered = _make_registered_repo()
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.get("/api/repos/10/files/content", params={"file_path": "src/missing.py"})

    assert response.status_code == 404


def test_pause_repo_indexing_sets_status_to_paused_when_currently_indexing() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/pause")

    assert response.status_code == 200
    assert response.json()["status"] == "paused"


def test_pause_repo_indexing_publishes_a_status_progress_message() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.INDEXING, total_files_expected=40)
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    client.post("/api/repos/10/pause")

    [message] = kafka_producer.published
    assert message.status == "paused"
    assert message.total_files_expected == 40


def test_pause_repo_indexing_rejects_a_repo_that_is_not_currently_indexing() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.PENDING)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/pause")

    assert response.status_code == 409


def test_pause_repo_indexing_returns_404_for_an_unregistered_repo() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos/999/pause")

    assert response.status_code == 404


def test_resume_repo_indexing_sets_status_to_indexing_when_paused() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.PAUSED)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/resume")

    assert response.status_code == 200
    assert response.json()["status"] == "indexing"


def test_resume_repo_indexing_republishes_a_repo_registered_message() -> None:
    """Resume reuses the exact registration flow so RepoIndexer re-walks and dispatches
    only files that have no IndexedFile row yet -- no separate resume-specific pipeline."""
    registered = _make_registered_repo(status=RepoIndexStatus.PAUSED)
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    client.post("/api/repos/10/resume")

    published_repo_registered = [message for message in kafka_producer.published if isinstance(message, RepoRegisteredMessage)]
    [message] = published_repo_registered
    assert message.repo_id == 10


def test_resume_repo_indexing_rejects_a_repo_that_is_not_paused() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/resume")

    assert response.status_code == 409


def test_resume_repo_indexing_returns_404_for_an_unregistered_repo() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos/999/resume")

    assert response.status_code == 404


def test_delete_registered_repo_removes_the_registration() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    user, cipher = _make_authenticated_user()
    session = FakeAsyncSession(existing=[registered])
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=session, current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.delete("/api/repos/10")

    assert response.status_code == 204
    assert session._rows == []


def test_delete_registered_repo_removes_its_indexed_files() -> None:
    registered = _make_registered_repo()
    files = [_make_indexed_file(id=1, file_path="a.py"), _make_indexed_file(id=2, file_path="b.py")]
    user, cipher = _make_authenticated_user()
    session = FakeAsyncSession(existing=[registered], indexed_files=files)
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=session, current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    client.delete("/api/repos/10")

    assert session._indexed_files == []


def test_delete_registered_repo_purges_the_vector_store() -> None:
    registered = _make_registered_repo()
    user, cipher = _make_authenticated_user()
    rag_manager = FakeRagManager()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
        rag_manager=rag_manager,
    )
    client = TestClient(app)

    client.delete("/api/repos/10")

    assert rag_manager.deleted_repo_ids == ["10"]


def test_delete_registered_repo_keeps_the_registration_when_the_purge_fails() -> None:
    """A failed vector-store purge must never leave the repo unregistered -- that would
    orphan indexed content nobody can authorize the presence of anymore."""
    registered = _make_registered_repo()
    user, cipher = _make_authenticated_user()
    session = FakeAsyncSession(existing=[registered])
    rag_manager = FakeRagManager(delete_error=VectorStoreDeletionError("pgvector unreachable"))
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=session,
        current_user=user,
        token_cipher=cipher,
        rag_manager=rag_manager,
    )
    client = TestClient(app)

    response = client.delete("/api/repos/10")

    assert response.status_code == 502
    assert session._rows == [registered]


def test_delete_registered_repo_returns_404_for_an_unregistered_repo() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.delete("/api/repos/999")

    assert response.status_code == 404


def test_retry_failed_files_sets_status_to_indexing_when_a_failed_file_exists() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.FAILED)
    failed_file = _make_indexed_file(status=IndexedFileStatus.FAILED, status_reason="boom")
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[failed_file]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/files/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "indexing"


def test_retry_failed_files_publishes_a_retry_and_a_status_progress_message() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.FAILED, total_files_expected=5)
    failed_file = _make_indexed_file(status=IndexedFileStatus.FAILED, status_reason="boom")
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[failed_file]),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    client.post("/api/repos/10/files/retry")

    [retry_message] = [m for m in kafka_producer.published if isinstance(m, RepoRegisteredMessage)]
    assert retry_message.repo_id == 10
    [status_message] = [m for m in kafka_producer.published if isinstance(m, RepoStatusProgressMessage)]
    assert status_message.status == "indexing"
    assert status_message.total_files_expected == 5


def test_retry_failed_files_is_a_no_op_when_nothing_failed() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[]),
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/files/retry")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert kafka_producer.published == []


def test_retry_failed_files_rejects_a_repo_that_has_not_finished_indexing() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    failed_file = _make_indexed_file(status=IndexedFileStatus.FAILED)
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=FakeAsyncSession(existing=[registered], indexed_files=[failed_file]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/files/retry")

    assert response.status_code == 409


def test_retry_failed_files_surfaces_a_kafka_publish_failure_as_a_bad_gateway() -> None:
    registered = _make_registered_repo(status=RepoIndexStatus.FAILED)
    failed_file = _make_indexed_file(status=IndexedFileStatus.FAILED)
    user, cipher = _make_authenticated_user()
    session = FakeAsyncSession(existing=[registered], indexed_files=[failed_file])
    kafka_producer = FakeRepoIndexProducer(publish_error=PublishError("broker unreachable"))
    app = _build_app(
        github_client=FakeGitHubOAuthClient(),
        session=session,
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/files/retry")

    assert response.status_code == 502
    assert registered.status == RepoIndexStatus.FAILED


def test_retry_failed_files_returns_404_for_an_unregistered_repo() -> None:
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(), session=FakeAsyncSession(), current_user=user, token_cipher=cipher
    )
    client = TestClient(app)

    response = client.post("/api/repos/999/files/retry")

    assert response.status_code == 404


def test_switch_repo_branch_purges_and_republishes() -> None:
    registered = _make_registered_repo(branch="main", commit_sha="abc123", status=RepoIndexStatus.COMPLETED)
    files = [_make_indexed_file()]
    user, cipher = _make_authenticated_user()
    kafka_producer = FakeRepoIndexProducer()
    rag_manager = FakeRagManager()
    session = FakeAsyncSession(existing=[registered], indexed_files=files)
    app = _build_app(
        github_client=FakeGitHubOAuthClient(commit_sha="feature-sha"),
        session=session,
        current_user=user,
        token_cipher=cipher,
        kafka_producer=kafka_producer,
        rag_manager=rag_manager,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/branch", json={"branch": "feature"})

    assert response.status_code == 200
    assert response.json()["branch"] == "feature"
    assert response.json()["status"] == "pending"
    assert rag_manager.deleted_repo_ids == ["10"]
    assert session._indexed_files == []
    [message] = kafka_producer.published
    assert message.branch == "feature"


def test_switch_repo_branch_rejects_a_branch_github_cannot_find() -> None:
    registered = _make_registered_repo(branch="main")
    user, cipher = _make_authenticated_user()
    app = _build_app(
        github_client=FakeGitHubOAuthClient(commit_fetch_error=GitHubCommitFetchError("not found")),
        session=FakeAsyncSession(existing=[registered]),
        current_user=user,
        token_cipher=cipher,
    )
    client = TestClient(app)

    response = client.post("/api/repos/10/branch", json={"branch": "does-not-exist"})

    assert response.status_code == 400
    assert registered.branch == "main"
