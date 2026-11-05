"""
    Tests that the review consumer reports its lifecycle to the metrics hook: queue wait when a worker starts a
    job, and how the pipeline run ended. The pipeline is replaced, since only the reporting around it is checked.
"""
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.observability.metrics import ApiMetrics
from api.review import review_consumer
from code_reviewer.pipeline.orchestrator import AGENT_EXECUTION_FAILED_REASON
from code_reviewer.schemas.review import CodeKey, SizeStatus, SkippedFile
from tests.api.review.test_review_consumer import (
    FakeAsyncSession,
    FakeProgressPublisher,
    _make_agent_entry,
    _make_consumer,
    _make_job,
    _make_message,
    _make_repo,
    _make_result,
)
from tests.metric_points import (
    REVIEW_DURATION,
    REVIEW_FILE_SIZE_STATUS,
    REVIEW_FILES,
    REVIEW_FILES_FAILED,
    REVIEW_FINISHED,
    REVIEW_QUEUE_WAIT,
    point_with,
    points_for,
)

_KIND = "code_reviewer.review_kind"
_RESULT = "code_reviewer.result"
_SIZE_STATUS = "code_reviewer.size_status"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the consumer at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(review_consumer, "api_metrics", isolated_api_metrics)


def _arrange(monkeypatch: pytest.MonkeyPatch, pipeline) -> tuple:
    review_msg = _make_message()
    job: ReviewJob = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[
            IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")
        ],
    )
    consumer = _make_consumer(session=session, broadcaster=FakeProgressPublisher())
    monkeypatch.setattr(review_consumer, "run_pipeline", pipeline)
    return consumer, review_msg, job


def _returning(result):
    async def pipeline(*args, **kwargs):
        return result

    return pipeline


async def _failing_pipeline(*args, **kwargs):
    raise RuntimeError("provider outage")


@pytest.mark.asyncio
async def test_queue_wait_is_the_time_since_the_job_was_created(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the wait recorded when a worker starts a job is measured from the job's creation."""
    consumer, review_msg, job = _arrange(monkeypatch, _returning(_make_result()))
    job.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=30)

    await consumer._run_review(review_msg)

    wait = point_with(metric_reader, REVIEW_QUEUE_WAIT, {_KIND: "repo"})
    assert 30 <= wait.sum < 60


@pytest.mark.asyncio
async def test_a_clean_run_is_recorded_as_completed(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a run with no failures inside it counts as completed and is timed."""
    consumer, review_msg, _ = _arrange(monkeypatch, _returning(_make_result()))

    await consumer._run_review(review_msg)

    assert point_with(metric_reader, REVIEW_FINISHED, {_KIND: "repo", _RESULT: "completed"}).value == 1
    assert point_with(metric_reader, REVIEW_DURATION, {_KIND: "repo", _RESULT: "completed"}).count == 1


@pytest.mark.asyncio
async def test_a_run_with_a_failed_agent_is_recorded_as_degraded(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a report that finished with an agent failure inside it counts as degraded, not completed."""
    degraded = _make_result(review=[_make_agent_entry(file_path="a.py", agents_failed=[CodeKey.SOLID1])])
    consumer, review_msg, _ = _arrange(monkeypatch, _returning(degraded))

    await consumer._run_review(review_msg)

    assert point_with(metric_reader, REVIEW_FINISHED, {_RESULT: "degraded"}).value == 1


@pytest.mark.asyncio
async def test_a_pipeline_that_raises_is_recorded_as_failed(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify an exception from the pipeline is timed and counted as failed, then still propagates."""
    consumer, review_msg, _ = _arrange(monkeypatch, _failing_pipeline)

    with pytest.raises(RuntimeError):
        await consumer._run_review(review_msg)

    assert point_with(metric_reader, REVIEW_FINISHED, {_KIND: "repo", _RESULT: "failed"}).value == 1
    assert points_for(metric_reader, REVIEW_FILES) == []


@pytest.mark.asyncio
async def test_a_job_that_already_finished_records_nothing(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a redelivered message for a finished job adds no queue wait and no run."""
    consumer, review_msg, job = _arrange(monkeypatch, _returning(_make_result()))
    job.status = ReviewJobStatus.COMPLETED

    with pytest.raises(review_consumer.ReviewAlreadyFinishedError):
        await consumer._run_review(review_msg)

    assert points_for(metric_reader, REVIEW_QUEUE_WAIT) == []
    assert points_for(metric_reader, REVIEW_FINISHED) == []


@pytest.mark.asyncio
async def test_the_report_shape_is_recorded_for_a_finished_review(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify file count, lost files and the size mix are reported from the finished report."""
    soft_limit_file = _make_agent_entry(file_path="b.py", agents_failed=[]).model_copy(
        update={"size_status": SizeStatus.SOFT_LIMIT}
    )
    report = _make_result(
        review=[_make_agent_entry(file_path="a.py", agents_failed=[]), soft_limit_file],
        skipped_files=[SkippedFile(file_path="c.py", reason=AGENT_EXECUTION_FAILED_REASON)],
    )
    consumer, review_msg, _ = _arrange(monkeypatch, _returning(report))

    await consumer._run_review(review_msg)

    files = point_with(metric_reader, REVIEW_FILES, {_KIND: "repo"})
    assert (files.count, files.sum) == (1, 2)
    assert point_with(metric_reader, REVIEW_FILES_FAILED, {_KIND: "repo"}).value == 1
    assert point_with(metric_reader, REVIEW_FILE_SIZE_STATUS, {_SIZE_STATUS: "normal"}).value == 1
    assert point_with(metric_reader, REVIEW_FILE_SIZE_STATUS, {_SIZE_STATUS: "soft_limit"}).value == 1
