"""
    Tests for RepoLifecycleService against fakes: no real DB, GitHub, Kafka or vector store.

    The HTTP-visible outcomes (status codes, published messages, state changes) are covered by
    tests/api/routers/test_repos.py; these cover behaviour a route test cannot observe.
"""
from datetime import datetime

import pytest
from pydantic import BaseModel

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.integrations.github import GitHubRepo
from api.repos.errors import RepoPurgeError
from api.repos.service import RepoIntegrations, RepoLifecycleService
from api.schemas.repos import RegisterRepoRequest
from code_reviewer.rag.errors import VectorStoreDeletionError


class FakeRepoStore:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self._calls = calls

    async def reject_active_registration(self, repo_id: int) -> None:
        return None

    async def add(self, registered: RegisteredRepo) -> None:
        self._calls.append(("add", registered.repo_id))

    async def remove(self, repo: RegisteredRepo) -> None:
        self._calls.append(("remove", repo.repo_id))

    async def has_failed_files(self, repo_id: int) -> bool:
        return True

    async def delete_indexed_files(self, repo_id: int) -> None:
        self._calls.append(("delete_indexed_files", repo_id))

    async def commit_changes(self) -> None:
        return None


class FakeGitHubClient:
    def __init__(self) -> None:
        self.repo_lookups: list[tuple[str, str]] = []
        self.branch_lookups: list[tuple[str, str, str]] = []

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        self.repo_lookups.append((access_token, full_name))
        return _make_github_repo()

    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str:
        self.branch_lookups.append((access_token, full_name, ref))
        return "def456"


class FakeDecryptor:
    def decrypt(self, encrypted_token: str) -> str:
        return f"decrypted:{encrypted_token}"


class FakeProducer:
    def __init__(self, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.attempts = 0

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None:
        self.attempts += 1
        if self._publish_error:
            raise self._publish_error


class FakeVectorStore:
    def __init__(self, calls: list[tuple[str, object]], delete_error: Exception | None = None) -> None:
        self._calls = calls
        self._delete_error = delete_error

    def delete_repo(self, repo_id: str) -> None:
        if self._delete_error:
            raise self._delete_error
        self._calls.append(("vector_store", repo_id))


def _make_user() -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token="cipher-text",
        github_granted_scopes="repo",
    )


def _make_github_repo() -> GitHubRepo:
    return GitHubRepo(
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        private=False,
        default_branch="main",
        language="Python",
        python_percentage=90.0,
        has_enough_python=True,
    )


def _make_registered_repo() -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        branch="main",
        registered_by_user_id=1,
        status=RepoIndexStatus.INDEXING,
        created_at=datetime(2026, 1, 1),
    )


def _build_service(
    *,
    calls: list[tuple[str, object]] | None = None,
    github_client: FakeGitHubClient | None = None,
    producer: FakeProducer | None = None,
    delete_error: Exception | None = None,
) -> RepoLifecycleService:
    recorded_calls = [] if calls is None else calls
    integrations = RepoIntegrations(
        github_client=github_client or FakeGitHubClient(),
        token_cipher=FakeDecryptor(),
        kafka_producer=producer or FakeProducer(),
        rag_manager=FakeVectorStore(recorded_calls, delete_error),
    )
    return RepoLifecycleService(FakeRepoStore(recorded_calls), integrations)


@pytest.mark.asyncio
async def test_register_queries_github_with_the_users_decrypted_token() -> None:
    """Verify that GitHub is asked with the registering user's own token.

    That is what makes a repo the user cannot see fail instead of being trusted.
    """
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    await service.register(RegisterRepoRequest(repo_id=10, full_name="octocat/hello-world"), _make_user())

    assert github_client.repo_lookups == [("decrypted:cipher-text", "octocat/hello-world")]


@pytest.mark.asyncio
async def test_switch_branch_checks_the_branch_with_the_users_decrypted_token() -> None:
    """Verify that the branch lookup targets the right repo and branch with the user's credentials."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    await service.switch_branch(_make_registered_repo(), "dev", _make_user())

    assert github_client.branch_lookups == [("decrypted:cipher-text", "octocat/hello-world", "dev")]


@pytest.mark.asyncio
async def test_delete_removes_the_vector_store_content_before_the_database_rows() -> None:
    """Verify the order: embeddings first, then file rows, then the registration.

    Registration goes last so a failure part-way leaves the repo registered and retryable.
    """
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls)

    await service.delete(_make_registered_repo())

    assert calls == [("vector_store", "10"), ("delete_indexed_files", 10), ("remove", 10)]


@pytest.mark.asyncio
async def test_delete_leaves_the_database_untouched_when_the_vector_store_purge_fails() -> None:
    """Verify that nothing else is deleted after the vector store fails."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls, delete_error=VectorStoreDeletionError("pgvector timeout"))

    with pytest.raises(RepoPurgeError, match="Could not purge this repo's indexed content"):
        await service.delete(_make_registered_repo())

    assert calls == []


@pytest.mark.asyncio
async def test_pause_still_succeeds_when_the_progress_notification_cannot_be_sent() -> None:
    """Verify that a lost live update never fails the request.

    The status change is already committed; only the notification is lost.
    """
    producer = FakeProducer(publish_error=RuntimeError("broker down"))
    repo = _make_registered_repo()
    service = _build_service(producer=producer)

    await service.pause(repo)

    assert (repo.status, producer.attempts) == (RepoIndexStatus.PAUSED, 1)
