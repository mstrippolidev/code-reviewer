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
from api.repos.errors import NotRepoOwnerError, RepoIdMismatchError, RepoPurgeError
from api.repos.service import RepoIntegrations, RepoLifecycleService
from api.schemas.repos import RegisterRepoRequest
from code_reviewer.rag.errors import VectorStoreDeletionError


class FakeRepoStore:
    def __init__(self, calls: list[tuple[str, object]], registered: RegisteredRepo | None = None) -> None:
        self._calls = calls
        self._registered = registered

    async def is_registered(self, repo_id: int) -> bool:
        return self._registered is not None

    async def find_by_repo_id(self, repo_id: int) -> RegisteredRepo:
        return self._registered

    async def add(self, registered: RegisteredRepo) -> None:
        self._calls.append(("add", registered.repo_id))

    async def add_link(self, user_id: int, repo_id: int) -> None:
        self._calls.append(("add_link", (user_id, repo_id)))

    async def remove_link(self, user_id: int, repo_id: int) -> None:
        self._calls.append(("remove_link", (user_id, repo_id)))

    async def remove(self, repo: RegisteredRepo) -> None:
        self._calls.append(("remove", repo.repo_id))

    async def has_failed_files(self, repo_id: int) -> bool:
        return True

    async def delete_indexed_files(self, repo_id: int) -> None:
        self._calls.append(("delete_indexed_files", repo_id))

    async def commit_changes(self) -> None:
        return None


class FakeGitHubClient:
    def __init__(self, repo: GitHubRepo | None = None) -> None:
        self._repo = repo
        self.repo_lookups: list[tuple[str, str]] = []
        self.branch_lookups: list[tuple[str, str, str]] = []

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        self.repo_lookups.append((access_token, full_name))
        return self._repo or _make_github_repo()

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


def _make_user(user_id: int = 1, token: str = "cipher-text") -> User:
    return User(
        id=user_id,
        github_id=user_id,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token=token,
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


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "branch": "main",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.INDEXING,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


def _build_service(
    *,
    calls: list[tuple[str, object]] | None = None,
    github_client: FakeGitHubClient | None = None,
    producer: FakeProducer | None = None,
    delete_error: Exception | None = None,
    registered: RegisteredRepo | None = None,
) -> RepoLifecycleService:
    recorded_calls = [] if calls is None else calls
    integrations = RepoIntegrations(
        github_client=github_client or FakeGitHubClient(),
        token_cipher=FakeDecryptor(),
        kafka_producer=producer or FakeProducer(),
        rag_manager=FakeVectorStore(recorded_calls, delete_error),
    )
    return RepoLifecycleService(FakeRepoStore(recorded_calls, registered), integrations)


REQUEST = RegisterRepoRequest(repo_id=10, full_name="octocat/hello-world")


@pytest.mark.asyncio
async def test_register_a_new_repo_queues_it_for_indexing() -> None:
    """Verify that a repo nobody registered yet goes to the indexing queue."""
    producer = FakeProducer()
    service = _build_service(producer=producer)

    await service.register(REQUEST, _make_user())

    assert producer.attempts == 1


@pytest.mark.asyncio
async def test_register_an_already_registered_repo_links_the_second_user() -> None:
    """Verify that a second user registering a healthy repo only gets their own link to it."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls, registered=_make_registered_repo(status=RepoIndexStatus.COMPLETED))

    await service.register(REQUEST, _make_user(user_id=2))

    assert calls == [("add_link", (2, 10))]


@pytest.mark.asyncio
async def test_register_an_already_registered_repo_returns_the_existing_repo() -> None:
    """Verify that the caller gets the shared repo back, not a copy."""
    existing = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    service = _build_service(registered=existing)

    assert await service.register(REQUEST, _make_user(user_id=2)) is existing


@pytest.mark.asyncio
async def test_register_an_already_registered_repo_does_not_queue_indexing() -> None:
    """Verify that linking a second user never re-indexes content that is already there."""
    producer = FakeProducer()
    service = _build_service(producer=producer, registered=_make_registered_repo(status=RepoIndexStatus.COMPLETED))

    await service.register(REQUEST, _make_user(user_id=2))

    assert producer.attempts == 0


@pytest.mark.asyncio
async def test_register_an_already_registered_repo_checks_github_with_the_callers_own_token() -> None:
    """Verify that the second user is verified with their token, not the owner's."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client, registered=_make_registered_repo())

    await service.register(REQUEST, _make_user(user_id=2, token="second-user-cipher"))

    assert github_client.repo_lookups == [("decrypted:second-user-cipher", "octocat/hello-world")]


@pytest.mark.asyncio
async def test_register_an_already_registered_repo_links_nobody_when_github_disagrees_on_the_repo_id() -> None:
    """Verify that a request whose repo_id does not match its full_name on GitHub is refused."""
    calls: list[tuple[str, object]] = []
    other_repo = _make_github_repo().model_copy(update={"repo_id": 77})
    service = _build_service(
        calls=calls, github_client=FakeGitHubClient(repo=other_repo), registered=_make_registered_repo()
    )

    with pytest.raises(RepoIdMismatchError):
        await service.register(REQUEST, _make_user(user_id=2))

    assert calls == []


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_resets_it_to_pending() -> None:
    """Verify that the owner registering a failed repo again starts it over in place."""
    failed = _make_registered_repo(status=RepoIndexStatus.FAILED, status_reason="tarball fetch failed")
    service = _build_service(registered=failed)

    await service.register(REQUEST, _make_user())

    assert (failed.status, failed.status_reason) == (RepoIndexStatus.PENDING, None)


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_queues_indexing_again() -> None:
    """Verify that the restart is actually sent to the indexing queue."""
    producer = FakeProducer()
    service = _build_service(producer=producer, registered=_make_registered_repo(status=RepoIndexStatus.FAILED))

    await service.register(REQUEST, _make_user())

    assert producer.attempts == 1


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_clears_the_old_content_first() -> None:
    """Verify that stale embeddings and file rows are removed before the new run starts."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls, registered=_make_registered_repo(status=RepoIndexStatus.FAILED))

    await service.register(REQUEST, _make_user())

    assert calls == [("vector_store", "10"), ("delete_indexed_files", 10)]


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_never_removes_the_repo_row() -> None:
    """Verify that restarting keeps the row, so every user's link to the repo survives."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls, registered=_make_registered_repo(status=RepoIndexStatus.FAILED))

    await service.register(REQUEST, _make_user())

    assert ("remove", 10) not in calls


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_switches_to_the_requested_branch() -> None:
    """Verify that a branch named in the request is honoured on restart."""
    failed = _make_registered_repo(status=RepoIndexStatus.FAILED)
    service = _build_service(registered=failed)

    await service.register(RegisterRepoRequest(repo_id=10, full_name="octocat/hello-world", branch="dev"), _make_user())

    assert failed.branch == "dev"


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_its_owner_keeps_the_branch_when_none_is_requested() -> None:
    """Verify that omitting the branch does not reset it to something else."""
    failed = _make_registered_repo(status=RepoIndexStatus.FAILED, branch="release")
    service = _build_service(registered=failed)

    await service.register(REQUEST, _make_user())

    assert failed.branch == "release"


@pytest.mark.asyncio
async def test_register_a_failed_repo_by_another_user_only_links_them() -> None:
    """Verify that only the owner can restart a failed repo; anyone else just gets a link."""
    calls: list[tuple[str, object]] = []
    producer = FakeProducer()
    failed = _make_registered_repo(status=RepoIndexStatus.FAILED)
    service = _build_service(calls=calls, producer=producer, registered=failed)

    await service.register(REQUEST, _make_user(user_id=2))

    assert (calls, producer.attempts, failed.status) == ([("add_link", (2, 10))], 0, RepoIndexStatus.FAILED)


@pytest.mark.asyncio
async def test_register_a_healthy_repo_by_its_owner_does_not_restart_it() -> None:
    """Verify that the owner registering their own working repo again changes nothing."""
    producer = FakeProducer()
    healthy = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    service = _build_service(producer=producer, registered=healthy)

    await service.register(REQUEST, _make_user())

    assert (producer.attempts, healthy.status) == (0, RepoIndexStatus.COMPLETED)


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

    await service.delete(_make_registered_repo(), _make_user())

    assert calls == [("vector_store", "10"), ("delete_indexed_files", 10), ("remove", 10)]


@pytest.mark.asyncio
async def test_delete_by_a_user_who_is_not_the_owner_only_removes_their_link() -> None:
    """Verify that a linked user leaving a repo neither purges its index nor deletes it for the others."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls)

    await service.delete(_make_registered_repo(registered_by_user_id=1), _make_user(user_id=2))

    assert calls == [("remove_link", (2, 10))]


@pytest.mark.asyncio
async def test_delete_leaves_the_database_untouched_when_the_vector_store_purge_fails() -> None:
    """Verify that nothing else is deleted after the vector store fails."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls, delete_error=VectorStoreDeletionError("pgvector timeout"))

    with pytest.raises(RepoPurgeError, match="Could not purge this repo's indexed content"):
        await service.delete(_make_registered_repo(), _make_user())

    assert calls == []


@pytest.mark.asyncio
async def test_pause_still_succeeds_when_the_progress_notification_cannot_be_sent() -> None:
    """Verify that a lost live update never fails the request.

    The status change is already committed; only the notification is lost.
    """
    producer = FakeProducer(publish_error=RuntimeError("broker down"))
    repo = _make_registered_repo()
    service = _build_service(producer=producer)

    await service.pause(repo, _make_user())

    assert (repo.status, producer.attempts) == (RepoIndexStatus.PAUSED, 1)


OWNER_ONLY_ACTIONS = [
    lambda service, repo, user: service.pause(repo, user),
    lambda service, repo, user: service.resume(repo, user),
    lambda service, repo, user: service.retry_failed_files(repo, user),
    lambda service, repo, user: service.switch_branch(repo, "dev", user),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", OWNER_ONLY_ACTIONS, ids=["pause", "resume", "retry", "switch_branch"])
async def test_owner_only_action_by_another_user_raises_not_owner(action) -> None:
    """Verify that pausing, resuming, retrying and switching branch are refused to a user who is not the owner."""
    service = _build_service()

    with pytest.raises(NotRepoOwnerError, match="Only the user who registered this repo"):
        await action(service, _make_registered_repo(registered_by_user_id=1), _make_user(user_id=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("action", OWNER_ONLY_ACTIONS, ids=["pause", "resume", "retry", "switch_branch"])
async def test_owner_only_action_by_another_user_changes_and_queues_nothing(action) -> None:
    """Verify that a refused action leaves the repo as it was and sends nothing to the queue."""
    producer = FakeProducer()
    calls: list[tuple[str, object]] = []
    repo = _make_registered_repo(registered_by_user_id=1, status=RepoIndexStatus.COMPLETED)
    service = _build_service(calls=calls, producer=producer)

    with pytest.raises(NotRepoOwnerError):
        await action(service, repo, _make_user(user_id=2))

    assert (repo.status, producer.attempts, calls) == (RepoIndexStatus.COMPLETED, 0, [])


@pytest.mark.asyncio
async def test_switch_branch_by_another_user_does_not_ask_github_about_the_branch() -> None:
    """Verify that a refused branch switch costs no GitHub call."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    with pytest.raises(NotRepoOwnerError):
        await service.switch_branch(_make_registered_repo(registered_by_user_id=1), "dev", _make_user(user_id=2))

    assert github_client.branch_lookups == []
