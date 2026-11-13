"""
    Tests for queueing exemplar nominations after a repo review finishes.
"""
import uuid

import pytest

from api.db.models.review_job import ReviewJob
from api.exemplars.publisher import ExemplarNominationPublisher
from api.exemplars.topics import EXEMPLAR_PROMOTION_REQUESTED
from api.indexing.producer import PublishError


class FakeProducer:
    def __init__(self, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[str, object, bytes]] = []

    async def publish(self, topic: str, message: object, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))


def _make_job(agent_entries: dict | None) -> ReviewJob:
    return ReviewJob(id=1, review_id=uuid.uuid4(), repo_id=10, file_paths=["a.py"], agent_entries=agent_entries)


@pytest.mark.asyncio
async def test_each_nomination_is_published_keyed_by_repo() -> None:
    """Verify one message per perfect file and agent, keyed by repo so one repo's decisions stay in order."""
    producer = FakeProducer()
    job = _make_job({"a.py": {"SOLID1": {"rating": 100}, "COH": {"rating": 100}}})

    await ExemplarNominationPublisher(producer).nominate(job)

    assert [(topic, key) for topic, _, key in producer.published] == [(EXEMPLAR_PROMOTION_REQUESTED, b"10")] * 2
    assert [message.code_key.value for _, message, _ in producer.published] == ["SOLID1", "COH"]


@pytest.mark.asyncio
async def test_a_job_with_no_stored_entries_publishes_nothing() -> None:
    """Verify a review that stored no per-agent entries is simply skipped."""
    producer = FakeProducer()

    await ExemplarNominationPublisher(producer).nominate(_make_job(None))

    assert producer.published == []


@pytest.mark.asyncio
async def test_a_publish_failure_is_swallowed() -> None:
    """Verify a broken queue cannot fail a review that already finished."""
    producer = FakeProducer(publish_error=PublishError("kafka down"))
    job = _make_job({"a.py": {"SOLID1": {"rating": 100}}})

    await ExemplarNominationPublisher(producer).nominate(job)

    assert producer.published == []
