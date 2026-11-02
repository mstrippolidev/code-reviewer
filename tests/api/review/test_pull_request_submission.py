"""
    Tests for PullRequestSubmissionService against fakes: no GitHub, no DB, no Kafka.
"""
from datetime import datetime

import pytest

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.indexing.producer import PublishError
from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import GitHubPullRequestFetchError, GitHubPullRequestNotFoundError
from api.repos.errors import GitHubAuthorizationExpiredError
from api.review.pull_request_errors import (
    PullRequestBaseBranchError,
    PullRequestNotFoundError,
    PullRequestNotOpenError,
    PullRequestQueueError,
    PullRequestRepoNotReadyError,
    PullRequestTooLargeError,
    PullRequestUnavailableError,
)
from api.review.pull_request_submission import (
    NOT_QUEUED_REASON,
    WAITING_FOR_INDEX_REASON,
    PullRequestSubmissionDependencies,
    PullRequestSubmissionService,
)
from api.review.topics import REVIEW_REQUESTED
from api.schemas.github import GitHubPullRequest
from api.schemas.pull_requests import PullRequestReviewRequest
from api.schemas.repos import RegisterRepoRequest
from api.schemas.reviews import ReviewRequestedMessage
from api.review.errors import TooManyUnfinishedReviewsError
from tests.api.fake_review_slots import FakeSlotKeeper

PR_URL = "https://github.com/acme/api/pull/7"
MAX_CHANGED_FILES = 100


class FakeGitHubClient:
    def __init__(self, pull_request: GitHubPullRequest | None = None, error: Exception | None = None) -> None:
        self._pull_request = pull_request or _pull_request()
        self._error = error
        self.calls: list[tuple[str, str, int]] = []

    async def fetch_pull_request(self, access_token: str, full_name: str, number: int) -> GitHubPullRequest:
        self.calls.append((access_token, full_name, number))
        if self._error:
            raise self._error
        return self._pull_request


class FakeTokenCipher:
    def decrypt(self, value: str) -> str:
        return f"plain-{value}"


class FakeRepository:
    def __init__(self, repo: RegisteredRepo | None) -> None:
        self._repo = repo

    async def is_registered(self, repo_id: int) -> bool:
        return self._repo is not None

    async def find_by_repo_id(self, repo_id: int) -> RegisteredRepo:
        return self._repo


class FakeLifecycleService:
    def __init__(self, registered: RegisteredRepo) -> None:
        self._registered = registered
        self.requests: list[RegisterRepoRequest] = []

    async def register(self, request: RegisterRepoRequest, user: User) -> RegisteredRepo:
        self.requests.append(request)
        return self._registered


class FakeProducer:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.published: list[tuple[str, ReviewRequestedMessage, bytes]] = []

    async def publish(self, topic: str, message: ReviewRequestedMessage, key: bytes) -> None:
        if self._error:
            raise self._error
        self.published.append((topic, message, key))


class FakeSession:
    def __init__(self) -> None:
        self.added: list[ReviewJob] = []
        self.commit_count = 0

    def add(self, row: ReviewJob) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, row: ReviewJob) -> None:
        return None


def _pull_request(**overrides) -> GitHubPullRequest:
    fields = {
        "number": 7,
        "state": "open",
        "merged": False,
        "head_sha": "head-sha",
        "base_ref": "main",
        "base_repo_id": 10,
        "base_repo_full_name": "acme/api",
        "changed_files": 3,
    }
    return GitHubPullRequest(**(fields | overrides))


def _repo(status: RepoIndexStatus = RepoIndexStatus.COMPLETED, branch: str = "main") -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="acme/api",
        default_branch="main",
        branch=branch,
        commit_sha="indexed-sha",
        registered_by_user_id=1,
        status=status,
        created_at=datetime(2026, 1, 1),
    )


def _user() -> User:
    return User(id=1, github_id=1, github_username="octocat", encrypted_github_token="secret")


class Harness:
    def __init__(
        self,
        *,
        registered: RegisteredRepo | None = None,
        registers_as: RegisteredRepo | None = None,
        github: FakeGitHubClient | None = None,
        producer: FakeProducer | None = None,
        slot_keeper: FakeSlotKeeper | None = None,
    ) -> None:
        self.session = FakeSession()
        self.slot_keeper = slot_keeper or FakeSlotKeeper()
        self.producer = producer or FakeProducer()
        self.github = github or FakeGitHubClient()
        self.lifecycle = FakeLifecycleService(registers_as or _repo(RepoIndexStatus.PENDING))
        self.service = PullRequestSubmissionService(
            PullRequestSubmissionDependencies(
                github_client=self.github,
                token_cipher=FakeTokenCipher(),
                repository=FakeRepository(registered),
                lifecycle_service=self.lifecycle,
                producer=self.producer,
                session=self.session,
                slot_keeper=self.slot_keeper,
                max_changed_files=MAX_CHANGED_FILES,
            )
        )

    async def submit(self, **request_fields) -> ReviewJob:
        return await self.service.submit(PullRequestReviewRequest(pr_url=PR_URL, **request_fields), _user())


@pytest.mark.asyncio
async def test_submit_for_an_indexed_repo_creates_a_job_pinned_to_the_head_commit() -> None:
    """Verify the review covers the commit that was current at submit time."""
    harness = Harness(registered=_repo())

    job = await harness.submit()

    assert (job.pr_number, job.head_sha, job.repo_id) == (7, "head-sha", 10)


@pytest.mark.asyncio
async def test_submit_for_an_indexed_repo_creates_a_pending_job_with_no_reason() -> None:
    """Verify a job that is queued at once does not claim to be waiting for anything."""
    job = await Harness(registered=_repo()).submit()

    assert (job.status, job.status_reason) == (ReviewJobStatus.PENDING, None)


@pytest.mark.asyncio
async def test_submit_records_who_asked_and_starts_with_no_files() -> None:
    """Verify the job belongs to the caller, and its file list is filled in later by the worker."""
    job = await Harness(registered=_repo()).submit()

    assert (job.requested_by_user_id, job.file_paths) == (1, [])


@pytest.mark.asyncio
async def test_submit_reserves_the_users_review_slot() -> None:
    """Verify the cap is taken atomically with the insert, for the user who asked."""
    harness = Harness(registered=_repo())

    await harness.submit()

    assert harness.slot_keeper.reserved == [1]


@pytest.mark.asyncio
async def test_submit_for_a_user_who_lost_the_race_for_the_last_slot_stores_nothing() -> None:
    """Verify a refused reservation leaves no job behind, even though the early check had passed."""
    harness = Harness(registered=_repo(), slot_keeper=FakeSlotKeeper(refusing_reservation_only=True))

    with pytest.raises(TooManyUnfinishedReviewsError):
        await harness.submit()

    assert harness.session.added == []


@pytest.mark.asyncio
async def test_submit_for_a_user_who_lost_the_race_for_the_last_slot_publishes_nothing() -> None:
    """Verify a refused reservation costs no review."""
    harness = Harness(registered=_repo(), slot_keeper=FakeSlotKeeper(refusing_reservation_only=True))

    with pytest.raises(TooManyUnfinishedReviewsError):
        await harness.submit()

    assert harness.producer.published == []


@pytest.mark.asyncio
async def test_submit_stores_the_requested_agents_on_the_job() -> None:
    """Verify the agent selection travels with the job."""
    job = await Harness(registered=_repo()).submit(agents=["TEST", "DRY"])

    assert job.agents == ["TEST", "DRY"]


@pytest.mark.asyncio
async def test_submit_for_an_indexed_repo_publishes_the_review_at_once() -> None:
    """Verify the worker is told about the pull request, by number and repo, with no files in the message."""
    harness = Harness(registered=_repo())

    job = await harness.submit()

    [(topic, message, key)] = harness.producer.published
    assert (topic, message.pr_number, message.repo_id, message.file_paths, key) == (
        REVIEW_REQUESTED,
        7,
        10,
        [],
        str(job.review_id).encode(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RepoIndexStatus.PENDING, RepoIndexStatus.INDEXING])
async def test_submit_for_a_repo_still_indexing_creates_a_waiting_job(status: RepoIndexStatus) -> None:
    """Verify the job says why it is not running yet, so a poller is not left guessing."""
    job = await Harness(registered=_repo(status)).submit()

    assert (job.status, job.status_reason) == (ReviewJobStatus.PENDING, WAITING_FOR_INDEX_REASON)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RepoIndexStatus.PENDING, RepoIndexStatus.INDEXING])
async def test_submit_for_a_repo_still_indexing_does_not_publish(status: RepoIndexStatus) -> None:
    """Verify nothing is sent to the worker until the index it needs exists."""
    harness = Harness(registered=_repo(status))

    await harness.submit()

    assert harness.producer.published == []


@pytest.mark.asyncio
async def test_submit_for_an_unregistered_repo_registers_it_by_github_id_following_the_base_branch() -> None:
    """Verify a new repo is indexed from the branch the pull request targets, under GitHub's own id and spelling."""
    harness = Harness(registered=None, github=FakeGitHubClient(_pull_request(base_ref="develop")))
    harness.lifecycle._registered = _repo(RepoIndexStatus.PENDING, branch="develop")

    await harness.submit()

    assert harness.lifecycle.requests == [RegisterRepoRequest(repo_id=10, full_name="acme/api", branch="develop")]


@pytest.mark.asyncio
async def test_submit_for_an_unregistered_repo_creates_a_waiting_job() -> None:
    """Verify the review starts only after the repo it was just registered for has been indexed."""
    job = await Harness(registered=None).submit()

    assert (job.status, job.status_reason) == (ReviewJobStatus.PENDING, WAITING_FOR_INDEX_REASON)


@pytest.mark.asyncio
async def test_submit_for_an_unregistered_repo_does_not_publish() -> None:
    """Verify an unindexed repo's review is not sent to the worker."""
    harness = Harness(registered=None)

    await harness.submit()

    assert harness.producer.published == []


@pytest.mark.asyncio
async def test_submit_for_a_registered_repo_does_not_register_it_again() -> None:
    """Verify an existing repo's index, owner and branch are left alone."""
    harness = Harness(registered=_repo())

    await harness.submit()

    assert harness.lifecycle.requests == []


@pytest.mark.asyncio
async def test_submit_reads_the_pull_request_with_the_users_decrypted_token() -> None:
    """Verify GitHub is asked as the user, which is also what proves they can see the pull request."""
    harness = Harness(registered=_repo())

    await harness.submit()

    assert harness.github.calls == [("plain-secret", "acme/api", 7)]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [RepoIndexStatus.FAILED, RepoIndexStatus.PAUSED])
async def test_submit_for_a_repo_that_cannot_make_progress_is_refused(status: RepoIndexStatus) -> None:
    """Verify a review is not left waiting forever behind an index that will not finish."""
    with pytest.raises(PullRequestRepoNotReadyError):
        await Harness(registered=_repo(status)).submit()


@pytest.mark.asyncio
async def test_submit_for_a_repo_that_cannot_make_progress_stores_nothing() -> None:
    """Verify a refused submission leaves no job behind."""
    harness = Harness(registered=_repo(RepoIndexStatus.FAILED))

    with pytest.raises(PullRequestRepoNotReadyError):
        await harness.submit()

    assert harness.session.added == []


@pytest.mark.asyncio
async def test_submit_for_a_pull_request_aimed_at_another_branch_is_refused() -> None:
    """Verify the review is not run against the history of the wrong branch."""
    harness = Harness(registered=_repo(branch="main"), github=FakeGitHubClient(_pull_request(base_ref="release")))

    with pytest.raises(PullRequestBaseBranchError, match="release.*main"):
        await harness.submit()


@pytest.mark.asyncio
async def test_submit_for_a_pull_request_aimed_at_another_branch_stores_nothing() -> None:
    """Verify a refused submission leaves no job behind."""
    harness = Harness(registered=_repo(branch="main"), github=FakeGitHubClient(_pull_request(base_ref="release")))

    with pytest.raises(PullRequestBaseBranchError):
        await harness.submit()

    assert harness.session.added == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields", [{"state": "closed"}, {"state": "closed", "merged": True}, {"state": "open", "merged": True}]
)
async def test_submit_for_a_pull_request_that_is_not_open_is_refused(fields: dict) -> None:
    """Verify only open pull requests are reviewed."""
    harness = Harness(registered=_repo(), github=FakeGitHubClient(_pull_request(**fields)))

    with pytest.raises(PullRequestNotOpenError):
        await harness.submit()


@pytest.mark.asyncio
async def test_submit_for_a_pull_request_over_the_file_limit_is_refused_before_anything_else() -> None:
    """Verify an oversized pull request is rejected on GitHub's own count, without registering or queuing."""
    harness = Harness(registered=None, github=FakeGitHubClient(_pull_request(changed_files=MAX_CHANGED_FILES + 1)))

    with pytest.raises(PullRequestTooLargeError):
        await harness.submit()

    assert (harness.lifecycle.requests, harness.session.added) == ([], [])


@pytest.mark.asyncio
async def test_submit_for_a_pull_request_at_exactly_the_file_limit_is_accepted() -> None:
    """Verify the limit is inclusive."""
    harness = Harness(registered=_repo(), github=FakeGitHubClient(_pull_request(changed_files=MAX_CHANGED_FILES)))

    job = await harness.submit()

    assert job.pr_number == 7


@pytest.mark.asyncio
async def test_submit_for_a_pull_request_github_cannot_find_says_so() -> None:
    """Verify a missing pull request, or one the user cannot see, is the same not-found."""
    harness = Harness(registered=_repo(), github=FakeGitHubClient(error=GitHubPullRequestNotFoundError("gone")))

    with pytest.raises(PullRequestNotFoundError):
        await harness.submit()


@pytest.mark.asyncio
async def test_submit_with_an_expired_github_login_asks_the_user_to_sign_in_again() -> None:
    """Verify an expired token is reported the way every other route reports it."""
    harness = Harness(registered=_repo(), github=FakeGitHubClient(error=GitHubTokenRejectedError("expired")))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await harness.submit()


@pytest.mark.asyncio
async def test_submit_when_github_fails_reports_it_as_unavailable() -> None:
    """Verify a GitHub outage is not mistaken for a missing pull request."""
    harness = Harness(registered=_repo(), github=FakeGitHubClient(error=GitHubPullRequestFetchError("down")))

    with pytest.raises(PullRequestUnavailableError):
        await harness.submit()


@pytest.mark.asyncio
async def test_submit_when_kafka_refuses_the_message_fails_the_job() -> None:
    """Verify a review that could not be queued is not left pending for a worker that will never see it."""
    harness = Harness(registered=_repo(), producer=FakeProducer(error=PublishError("kafka down")))

    with pytest.raises(PullRequestQueueError):
        await harness.submit()

    job = harness.session.added[0]
    assert (job.status, job.status_reason) == (ReviewJobStatus.FAILED, NOT_QUEUED_REASON)
