"""
    The pull request branch of ReviewRequestConsumer against fakes: the loader and the pipeline are replaced,
    so these cover how the consumer uses them, and what it does when they fail.
"""
import pytest

from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.integrations.github_pull_requests import GitHubPullRequestFetchError
from api.review import review_consumer
from api.review.pull_request_loader import LoadedPullRequest, PullRequestReviewUnavailableError
from api.review.topics import REVIEW_REQUESTED_DLQ
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import AggregatorOutput, SkippedFile
from code_reviewer.schemas.submission import SubmittedFile
from tests.api.review.test_review_consumer import (
    FakeAsyncSession,
    FakeConsumerRecord,
    FakeDlqProducer,
    FakeProgressPublisher,
    _make_consumer,
    _make_job,
    _make_message,
    _make_repo,
    _make_result,
)

PR_FILES = [SubmittedFile(file_path="a.py", content="x = 1\n"), SubmittedFile(file_path="test_a.py", content="")]
UNREADABLE = [SkippedFile(file_path="big.py", reason="pr_file_unreadable")]


class FakeLoader:
    """Stands in for PullRequestSubmissionLoader: sets the job's file list as the real one does, or fails."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls = 0

    async def load(self, job: ReviewJob, repo, session) -> LoadedPullRequest:
        self.calls += 1
        if self._error:
            raise self._error
        job.file_paths = [file.file_path for file in PR_FILES]
        return LoadedPullRequest(files=PR_FILES, skipped=UNREADABLE)


class CapturingPipeline:
    def __init__(self) -> None:
        self.files: list[SubmittedFile] | None = None
        self.repo_data: RepoData | None = None

    async def __call__(self, files, agents_container, repo_data, **kwargs) -> AggregatorOutput:
        self.files = files
        self.repo_data = repo_data
        return _make_result()


def _setup(monkeypatch: pytest.MonkeyPatch, loader: FakeLoader):
    review_msg = _make_message(pr_number=7, file_paths=[])
    job = _make_job(review_msg)
    job.pr_number = 7
    job.head_sha = "head-sha"
    session = FakeAsyncSession(registered_repo=_make_repo(), review_job=job)
    publisher = FakeProgressPublisher()
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(
        session=session, broadcaster=publisher, dlq_producer=dlq_producer, pull_request_loader=loader
    )
    pipeline = CapturingPipeline()
    monkeypatch.setattr(review_consumer, "run_pipeline", pipeline)
    return consumer, review_msg, job, publisher, dlq_producer, pipeline


async def _deliver(consumer, review_msg) -> None:
    raw_msg = FakeConsumerRecord(value=review_msg.model_dump_json().encode(), key=str(review_msg.review_id).encode())
    await consumer._handle_parsed_message(review_msg, msg=raw_msg, consumer=None)


@pytest.mark.asyncio
async def test_pull_request_review_hands_the_fetched_files_to_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the pipeline reviews what was read from GitHub, sources and tests together so it can pair them."""
    consumer, review_msg, _job, _publisher, _dlq, pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    assert pipeline.files == PR_FILES


@pytest.mark.asyncio
async def test_pull_request_review_runs_the_pipeline_with_the_repos_scoping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify DRY, ARCH, COUP and the corpus-wide test pairing compare against this repo's index."""
    consumer, review_msg, _job, _publisher, _dlq, pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    assert pipeline.repo_data == RepoData(repo_id="10", commit_sha="abc123", owner_id="99")


@pytest.mark.asyncio
async def test_pull_request_review_completes_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a pull request review reaches the same final state as any other review."""
    consumer, review_msg, job, _publisher, _dlq, _pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    assert job.status == ReviewJobStatus.COMPLETED


@pytest.mark.asyncio
async def test_pull_request_review_lists_unreadable_files_in_the_report(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a changed file that could not be read is reported as skipped, not silently missing."""
    consumer, review_msg, job, _publisher, _dlq, _pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    skipped = job.result["meta"]["skipped_files"]
    assert skipped == [{"file_path": "big.py", "reason": "pr_file_unreadable"}]


@pytest.mark.asyncio
async def test_pull_request_review_unreadable_files_do_not_raise_a_dead_letter_alert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a file GitHub cannot return is an ordinary skip, not a pipeline failure someone must investigate."""
    consumer, review_msg, _job, _publisher, dlq_producer, _pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    assert dlq_producer.published == []


@pytest.mark.asyncio
async def test_pull_request_review_tells_clients_the_file_list_once_it_is_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a poller or stream sees the real files soon after the review starts, not an empty list until it ends."""
    consumer, review_msg, _job, publisher, _dlq, _pipeline = _setup(monkeypatch, FakeLoader())

    await _deliver(consumer, review_msg)

    assert publisher.published[1].file_paths == ["a.py", "test_a.py"]


@pytest.mark.asyncio
async def test_pull_request_review_the_user_can_act_on_fails_the_job_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an expired GitHub login or an empty pull request is explained to the user on the job itself."""
    loader = FakeLoader(error=PullRequestReviewUnavailableError("Sign in again"))
    consumer, review_msg, job, _publisher, _dlq, _pipeline = _setup(monkeypatch, loader)

    await _deliver(consumer, review_msg)

    assert (job.status, job.status_reason) == (ReviewJobStatus.FAILED, "Sign in again")


@pytest.mark.asyncio
async def test_pull_request_review_the_user_can_act_on_is_not_sent_to_the_dead_letter_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a problem the user fixes themselves does not page whoever watches the dead-letter topic."""
    loader = FakeLoader(error=PullRequestReviewUnavailableError("Sign in again"))
    consumer, review_msg, _job, _publisher, dlq_producer, _pipeline = _setup(monkeypatch, loader)

    await _deliver(consumer, review_msg)

    assert dlq_producer.published == []


@pytest.mark.asyncio
async def test_pull_request_review_the_user_can_act_on_never_runs_the_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a review that cannot read its files spends no LLM money."""
    loader = FakeLoader(error=PullRequestReviewUnavailableError("Sign in again"))
    consumer, review_msg, _job, _publisher, _dlq, pipeline = _setup(monkeypatch, loader)

    await _deliver(consumer, review_msg)

    assert pipeline.files is None


@pytest.mark.asyncio
async def test_pull_request_review_with_a_github_outage_fails_the_job_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an infrastructure failure is treated like any other unexpected review failure."""
    loader = FakeLoader(error=GitHubPullRequestFetchError("github is down"))
    consumer, review_msg, job, _publisher, dlq_producer, _pipeline = _setup(monkeypatch, loader)

    await _deliver(consumer, review_msg)

    assert job.status == ReviewJobStatus.FAILED
    assert dlq_producer.published[0][0] == REVIEW_REQUESTED_DLQ
