"""Registration without a client-supplied repo_id, and validation of a requested branch."""
import pytest
from pydantic import BaseModel

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.indexing.topics import REPO_REGISTERED
from api.integrations.github import GitHubCommitFetchError, GitHubRepoFetchError
from api.repos.errors import BranchNotFoundError, GitHubVerificationUnavailableError, InsufficientPythonError
from api.schemas.repos import RegisterRepoRequest
from tests.api.repos.test_service import (
    FakeGitHubClient,
    FakeProducer,
    FakeRepoStore,
    _build_service,
    _make_github_repo,
    _make_registered_repo,
    _make_user,
)

FULL_NAME = "octocat/hello-world"
NAME_ONLY_REQUEST = RegisterRepoRequest(full_name=FULL_NAME)


class GitHubClientWithoutBranch(FakeGitHubClient):
    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str:
        raise GitHubCommitFetchError("branch not found")


class GitHubClientThatCannotFetchRepo(FakeGitHubClient):
    async def fetch_repo(self, access_token: str, full_name: str):
        raise GitHubRepoFetchError("GitHub unreachable")


class RecordingProducer(FakeProducer):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[tuple[str, BaseModel]] = []

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None:
        self.published.append((topic, message))
        await super().publish(topic, message, key)


class RecordingRepoStore(FakeRepoStore):
    def __init__(self) -> None:
        super().__init__([])
        self.added: list[RegisteredRepo] = []

    async def add(self, registered: RegisteredRepo) -> None:
        self.added.append(registered)


async def _register_and_get_stored_repo(request: RegisterRepoRequest) -> RegisteredRepo:
    store = RecordingRepoStore()
    await _build_service(store=store).register(request, _make_user())
    return store.added[0]


@pytest.mark.asyncio
async def test_register_without_repo_id_registers_the_repo_id_github_reports() -> None:
    """Verify that the repo id GitHub returns for the full name is the one stored."""
    calls: list[tuple[str, object]] = []
    service = _build_service(calls=calls)

    await service.register(NAME_ONLY_REQUEST, _make_user())

    assert calls == [("add", 10)]


@pytest.mark.asyncio
async def test_register_without_repo_id_asks_github_once() -> None:
    """Verify that resolving the id and verifying the repo share one GitHub lookup."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    await service.register(NAME_ONLY_REQUEST, _make_user())

    assert len(github_client.repo_lookups) == 1


@pytest.mark.asyncio
async def test_register_without_repo_id_links_the_user_to_an_already_registered_repo() -> None:
    """Verify that a name-only request finds the repo GitHub names and links the caller to it."""
    calls: list[tuple[str, object]] = []
    registered = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    service = _build_service(calls=calls, registered=registered)

    await service.register(NAME_ONLY_REQUEST, _make_user(user_id=2))

    assert calls == [("add_link", (2, 10))]


@pytest.mark.asyncio
async def test_register_with_a_branch_checks_it_with_the_callers_own_token() -> None:
    """Verify that a requested branch is looked up on GitHub for the right repo and user."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    await service.register(RegisterRepoRequest(full_name=FULL_NAME, branch="dev"), _make_user())

    assert github_client.branch_lookups == [("decrypted:cipher-text", FULL_NAME, "dev")]


@pytest.mark.asyncio
async def test_register_without_a_branch_does_not_look_one_up() -> None:
    """Verify that the repo's default branch is used without an extra GitHub call."""
    github_client = FakeGitHubClient()
    service = _build_service(github_client=github_client)

    await service.register(NAME_ONLY_REQUEST, _make_user())

    assert github_client.branch_lookups == []


@pytest.mark.asyncio
async def test_register_with_an_unknown_branch_raises_branch_not_found() -> None:
    """Verify that a branch GitHub does not know is refused before anything is registered."""
    service = _build_service(github_client=GitHubClientWithoutBranch())

    with pytest.raises(BranchNotFoundError):
        await service.register(RegisterRepoRequest(full_name=FULL_NAME, branch="mian"), _make_user())


@pytest.mark.asyncio
async def test_register_with_an_unknown_branch_queues_no_indexing() -> None:
    """Verify that a typo in the branch name never starts an indexing job."""
    producer = FakeProducer()
    service = _build_service(github_client=GitHubClientWithoutBranch(), producer=producer)

    with pytest.raises(BranchNotFoundError):
        await service.register(RegisterRepoRequest(full_name=FULL_NAME, branch="mian"), _make_user())

    assert producer.attempts == 0


@pytest.mark.asyncio
async def test_register_without_a_branch_tracks_the_repos_default_branch() -> None:
    """Verify that a new repo with no requested branch is tracked on GitHub's default branch."""
    stored = await _register_and_get_stored_repo(NAME_ONLY_REQUEST)

    assert stored.branch == "main"


@pytest.mark.asyncio
async def test_register_with_a_branch_tracks_the_requested_branch() -> None:
    """Verify that a requested branch is the one stored, while the default branch stays informational."""
    stored = await _register_and_get_stored_repo(RegisterRepoRequest(full_name=FULL_NAME, branch="dev"))

    assert (stored.branch, stored.default_branch) == ("dev", "main")


@pytest.mark.asyncio
async def test_register_takes_the_owner_id_from_github() -> None:
    """Verify that the stored owner id comes from GitHub, never from the client's request."""
    stored = await _register_and_get_stored_repo(NAME_ONLY_REQUEST)

    assert stored.owner_id == _make_github_repo().owner_id


@pytest.mark.asyncio
async def test_register_starts_a_new_repo_as_pending_for_the_registering_user() -> None:
    """Verify that a new repo waits for indexing and is owned by the user who registered it."""
    stored = await _register_and_get_stored_repo(NAME_ONLY_REQUEST)

    assert (stored.status, stored.registered_by_user_id) == (RepoIndexStatus.PENDING, _make_user().id)


@pytest.mark.asyncio
async def test_register_a_repo_with_too_little_python_raises_insufficient_python() -> None:
    """Verify that a repo below the Python threshold is refused."""
    mostly_javascript = _make_github_repo().model_copy(update={"has_enough_python": False, "python_percentage": 10.0})
    service = _build_service(github_client=FakeGitHubClient(repo=mostly_javascript))

    with pytest.raises(InsufficientPythonError):
        await service.register(NAME_ONLY_REQUEST, _make_user())


@pytest.mark.asyncio
async def test_register_a_repo_with_too_little_python_queues_no_indexing() -> None:
    """Verify that a refused repo is never queued for indexing."""
    mostly_javascript = _make_github_repo().model_copy(update={"has_enough_python": False, "python_percentage": 10.0})
    producer = FakeProducer()
    service = _build_service(github_client=FakeGitHubClient(repo=mostly_javascript), producer=producer)

    with pytest.raises(InsufficientPythonError):
        await service.register(NAME_ONLY_REQUEST, _make_user())

    assert producer.attempts == 0


@pytest.mark.asyncio
async def test_register_when_github_cannot_be_reached_raises_verification_unavailable() -> None:
    """Verify that a GitHub outage is reported as unavailable, not as a missing repo."""
    service = _build_service(github_client=GitHubClientThatCannotFetchRepo())

    with pytest.raises(GitHubVerificationUnavailableError):
        await service.register(NAME_ONLY_REQUEST, _make_user())


@pytest.mark.asyncio
async def test_register_when_github_cannot_be_reached_registers_nothing() -> None:
    """Verify that a failed GitHub lookup leaves no registration and no queued job behind."""
    store = RecordingRepoStore()
    producer = FakeProducer()
    service = _build_service(github_client=GitHubClientThatCannotFetchRepo(), store=store, producer=producer)

    with pytest.raises(GitHubVerificationUnavailableError):
        await service.register(NAME_ONLY_REQUEST, _make_user())

    assert (store.added, producer.attempts) == ([], 0)


@pytest.mark.asyncio
async def test_register_a_new_repo_publishes_the_registered_event_for_its_repo_id() -> None:
    """Verify that the indexing pipeline is told about exactly the repo that was registered."""
    producer = RecordingProducer()
    service = _build_service(producer=producer)

    await service.register(NAME_ONLY_REQUEST, _make_user())

    topic, message = producer.published[0]
    assert (topic, message.repo_id) == (REPO_REGISTERED, 10)


@pytest.mark.asyncio
async def test_register_a_new_repo_returns_the_repo_it_stored() -> None:
    """Verify that the caller gets back the same registration that was saved, not a copy."""
    store = RecordingRepoStore()

    returned = await _build_service(store=store).register(NAME_ONLY_REQUEST, _make_user())

    assert returned is store.added[0]


@pytest.mark.asyncio
async def test_register_stores_the_full_name_as_github_spells_it() -> None:
    """Verify that a request typed in another casing is stored under GitHub's canonical name."""
    stored = await _register_and_get_stored_repo(RegisterRepoRequest(full_name="OCTOCAT/Hello-World"))

    assert stored.full_name == "octocat/hello-world"
