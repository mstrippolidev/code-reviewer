"""
    Tests for PendingPullRequestReleaser against fakes: no DB, no Kafka.
"""
import uuid
from datetime import datetime

import pytest

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.indexing.producer import PublishError
from api.review.pull_request_queue import NOT_QUEUED_REASON
from api.review.pull_request_release import INDEX_FAILED_REASON, PendingPullRequestReleaser
from api.review.topics import REVIEW_REQUESTED
from api.schemas.reviews import ReviewRequestedMessage


class FakeProducer:
    def __init__(self, fail_for: set[uuid.UUID] | None = None) -> None:
        self._fail_for = fail_for or set()
        self.published: list[tuple[str, ReviewRequestedMessage, bytes]] = []

    async def publish(self, topic: str, message: ReviewRequestedMessage, key: bytes) -> None:
        if message.review_id in self._fail_for:
            raise PublishError("kafka down")
        self.published.append((topic, message, key))


class _ScalarsResult:
    def __init__(self, items: list[ReviewJob]) -> None:
        self._items = items

    def all(self) -> list[ReviewJob]:
        return self._items


class FakeSession:
    """Returns the pending pull request jobs it was seeded with and counts commits."""

    def __init__(self, jobs: list[ReviewJob]) -> None:
        self._jobs = jobs
        self.commit_count = 0

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult(self._jobs)

    async def commit(self) -> None:
        self.commit_count += 1


def _repo() -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="acme/api",
        default_branch="main",
        branch="main",
        commit_sha="indexed-sha",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
        created_at=datetime(2026, 1, 1),
    )


def _job(pr_number: int = 7, agents: list[str] | None = None) -> ReviewJob:
    return ReviewJob(
        id=pr_number,
        review_id=uuid.uuid4(),
        repo_id=10,
        requested_by_user_id=1,
        file_paths=[],
        pr_number=pr_number,
        head_sha="head-sha",
        agents=agents,
        status=ReviewJobStatus.PENDING,
        status_reason="Waiting for the repo to finish indexing",
    )


@pytest.mark.asyncio
async def test_release_publishes_each_waiting_pull_request_review() -> None:
    """Verify every review that waited for the index is sent to the worker."""
    jobs = [_job(7), _job(8)]
    producer = FakeProducer()

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession(jobs))

    assert [message.pr_number for _topic, message, _key in producer.published] == [7, 8]


@pytest.mark.asyncio
async def test_release_publishes_to_the_review_topic_keyed_by_review_id() -> None:
    """Verify the same topic and key as a review submitted when the repo was already indexed."""
    job = _job()
    producer = FakeProducer()

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession([job]))

    [(topic, _message, key)] = producer.published
    assert (topic, key) == (REVIEW_REQUESTED, str(job.review_id).encode())


@pytest.mark.asyncio
async def test_release_carries_the_repo_owner_and_the_agent_selection() -> None:
    """Verify a released message is complete: whose repo, who asked, and which agents to run."""
    job = _job(agents=["TEST"])
    producer = FakeProducer()

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession([job]))

    message = producer.published[0][1]
    assert (message.repo_id, message.owner_id, message.requested_by_user_id, message.agents) == (10, 99, 1, ["TEST"])


@pytest.mark.asyncio
async def test_release_clears_the_waiting_reason() -> None:
    """Verify a poller no longer reads "waiting" for a review that has been handed to the worker."""
    job = _job()

    await PendingPullRequestReleaser(FakeProducer()).release(_repo(), FakeSession([job]))

    assert job.status_reason is None


@pytest.mark.asyncio
async def test_release_leaves_the_job_pending_for_the_worker_to_start() -> None:
    """Verify only the worker moves a review to running."""
    job = _job()

    await PendingPullRequestReleaser(FakeProducer()).release(_repo(), FakeSession([job]))

    assert job.status == ReviewJobStatus.PENDING


@pytest.mark.asyncio
async def test_release_fails_a_review_whose_message_cannot_be_published() -> None:
    """Verify a review Kafka refused is not left pending forever."""
    job = _job()
    producer = FakeProducer(fail_for={job.review_id})

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession([job]))

    assert (job.status, job.status_reason) == (ReviewJobStatus.FAILED, NOT_QUEUED_REASON)


@pytest.mark.asyncio
async def test_release_still_publishes_the_other_reviews_when_one_fails() -> None:
    """Verify one refused message does not strand the reviews behind it."""
    failing, healthy = _job(7), _job(8)
    producer = FakeProducer(fail_for={failing.review_id})

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession([failing, healthy]))

    assert [message.pr_number for _topic, message, _key in producer.published] == [8]


@pytest.mark.asyncio
async def test_release_commits_once_for_all_the_reviews() -> None:
    """Verify the status changes are saved together."""
    session = FakeSession([_job(7), _job(8)])

    await PendingPullRequestReleaser(FakeProducer()).release(_repo(), session)

    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_release_with_no_waiting_reviews_publishes_nothing() -> None:
    """Verify a repo that completes with nobody waiting does no work."""
    producer = FakeProducer()

    await PendingPullRequestReleaser(producer).release(_repo(), FakeSession([]))

    assert producer.published == []


@pytest.mark.asyncio
async def test_fail_marks_each_waiting_review_failed_with_the_indexing_reason() -> None:
    """Verify a review behind a repo that could not be indexed says why it will never run."""
    jobs = [_job(7), _job(8)]

    await PendingPullRequestReleaser(FakeProducer()).fail(10, FakeSession(jobs))

    assert [(job.status, job.status_reason) for job in jobs] == [(ReviewJobStatus.FAILED, INDEX_FAILED_REASON)] * 2


@pytest.mark.asyncio
async def test_fail_publishes_nothing() -> None:
    """Verify a failed repo's reviews are not sent to the worker."""
    producer = FakeProducer()

    await PendingPullRequestReleaser(producer).fail(10, FakeSession([_job()]))

    assert producer.published == []


@pytest.mark.asyncio
async def test_fail_commits_the_new_statuses() -> None:
    """Verify the failure is saved."""
    session = FakeSession([_job()])

    await PendingPullRequestReleaser(FakeProducer()).fail(10, session)

    assert session.commit_count == 1
