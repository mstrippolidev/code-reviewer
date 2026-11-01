"""
    A review.requested message that arrives for a job in a given state: finished jobs are left alone,
    an interrupted one is run again. Fakes only; the pipeline is replaced.
"""
import pytest

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.review import review_consumer
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


class RecordingPipeline:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        return _make_result()


def _consumer_for(job_status: ReviewJobStatus, monkeypatch: pytest.MonkeyPatch):
    review_msg = _make_message()
    job: ReviewJob = _make_job(review_msg)
    job.status = job_status
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[
            IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")
        ],
    )
    pipeline = RecordingPipeline()
    monkeypatch.setattr(review_consumer, "run_pipeline", pipeline)
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(session=session, broadcaster=FakeProgressPublisher(), dlq_producer=dlq_producer)
    return consumer, review_msg, job, pipeline, dlq_producer


async def _deliver(consumer, review_msg) -> None:
    raw_msg = FakeConsumerRecord(value=review_msg.model_dump_json().encode(), key=str(review_msg.review_id).encode())
    await consumer._handle_parsed_message(review_msg, msg=raw_msg, consumer=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("final_status", [ReviewJobStatus.COMPLETED, ReviewJobStatus.FAILED])
async def test_message_for_a_finished_job_does_not_run_the_pipeline_again(
    monkeypatch: pytest.MonkeyPatch, final_status: ReviewJobStatus
) -> None:
    """Verify a redelivered or duplicated message cannot spend LLM money twice on the same review."""
    consumer, review_msg, _job, pipeline, _dlq = _consumer_for(final_status, monkeypatch)

    await _deliver(consumer, review_msg)

    assert pipeline.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("final_status", [ReviewJobStatus.COMPLETED, ReviewJobStatus.FAILED])
async def test_message_for_a_finished_job_leaves_its_status_alone(
    monkeypatch: pytest.MonkeyPatch, final_status: ReviewJobStatus
) -> None:
    """Verify a finished review is not reopened or overwritten."""
    consumer, review_msg, job, _pipeline, _dlq = _consumer_for(final_status, monkeypatch)

    await _deliver(consumer, review_msg)

    assert job.status == final_status


@pytest.mark.asyncio
async def test_message_for_a_finished_job_is_not_sent_to_the_dead_letter_topic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify skipping a duplicate is routine and does not raise an alert."""
    consumer, review_msg, _job, _pipeline, dlq_producer = _consumer_for(ReviewJobStatus.COMPLETED, monkeypatch)

    await _deliver(consumer, review_msg)

    assert dlq_producer.published == []


@pytest.mark.asyncio
async def test_message_for_a_job_left_running_by_a_crash_runs_the_pipeline_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a review interrupted by a restart is still recovered when Kafka redelivers its message."""
    consumer, review_msg, _job, pipeline, _dlq = _consumer_for(ReviewJobStatus.RUNNING, monkeypatch)

    await _deliver(consumer, review_msg)

    assert pipeline.calls == 1


@pytest.mark.asyncio
async def test_message_for_a_pending_job_runs_the_pipeline_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the normal case is unchanged by the guard."""
    consumer, review_msg, job, pipeline, _dlq = _consumer_for(ReviewJobStatus.PENDING, monkeypatch)

    await _deliver(consumer, review_msg)

    assert (pipeline.calls, job.status) == (1, ReviewJobStatus.COMPLETED)
