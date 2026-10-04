"""
    Tests for the review.progress relay against fakes: no real Kafka broker.
"""
import uuid

import pytest
from pydantic import BaseModel

from api.db.models.review_job import ReviewJobStatus
from api.indexing.producer import PublishError
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster
from api.review.review_progress_consumer import ReviewProgressConsumer, ReviewProgressMessageParseError
from api.review.review_progress_publisher import KafkaReviewProgressPublisher
from api.review.topics import REVIEW_PROGRESS
from api.schemas.reviews import ReviewFileProgressMessage, ReviewStatusMessage

REVIEW_ID = uuid.UUID("b6d01287-5d3e-45b8-a1e3-730254b25969")


class FakeProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[str, BaseModel, bytes]] = []

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))


class FakeConsumerRecord:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.offset = 0


class FakeKafkaConsumer:
    async def commit(self) -> None:
        return None


class RecordingBroadcaster(ReviewProgressBroadcaster):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple[uuid.UUID, object]] = []

    async def publish(self, review_id: uuid.UUID, event: object) -> None:
        self.received.append((review_id, event))


def _file_event() -> ReviewFileProgressMessage:
    return ReviewFileProgressMessage(review_id=REVIEW_ID, file_path="examples/payment_processor.py", failed=False)


def _completed_status_event() -> ReviewStatusMessage:
    return ReviewStatusMessage(
        review_id=REVIEW_ID,
        repo_id=None,
        status=ReviewJobStatus.COMPLETED,
        status_reason=None,
        file_paths=["examples/payment_processor.py"],
    )


async def _publish_and_capture_bytes(event: object) -> bytes:
    producer = FakeProducer()
    await KafkaReviewProgressPublisher(producer).publish(REVIEW_ID, event)
    [(_topic, message, _key)] = producer.published
    return message.model_dump_json().encode()


@pytest.mark.asyncio
async def test_publisher_sends_to_the_review_progress_topic() -> None:
    """Verify progress goes to the topic every replica listens on."""
    producer = FakeProducer()

    await KafkaReviewProgressPublisher(producer).publish(REVIEW_ID, _file_event())

    assert producer.published[0][0] == REVIEW_PROGRESS


@pytest.mark.asyncio
async def test_publisher_keys_messages_by_review_id() -> None:
    """Verify one review's events share a partition, so a terminal status can never overtake its file events."""
    producer = FakeProducer()

    await KafkaReviewProgressPublisher(producer).publish(REVIEW_ID, _file_event())

    assert producer.published[0][2] == str(REVIEW_ID).encode()


@pytest.mark.asyncio
async def test_publisher_swallows_a_kafka_failure() -> None:
    """Verify a progress-delivery failure never fails the review job itself."""
    producer = FakeProducer(publish_error=PublishError("broker down"))

    await KafkaReviewProgressPublisher(producer).publish(REVIEW_ID, _file_event())

    assert producer.published == []


@pytest.mark.asyncio
async def test_file_event_survives_the_round_trip_through_kafka() -> None:
    """Verify what the publisher writes is exactly what the consumer reads back."""
    consumer = ReviewProgressConsumer(RecordingBroadcaster())
    published_bytes = await _publish_and_capture_bytes(_file_event())

    parsed = consumer._parse_msg(FakeConsumerRecord(published_bytes))

    assert parsed == _file_event()


@pytest.mark.asyncio
async def test_status_event_survives_the_round_trip_through_kafka() -> None:
    """Verify the terminal status, which ends the browser's stream, is not mistaken for another event type."""
    consumer = ReviewProgressConsumer(RecordingBroadcaster())
    published_bytes = await _publish_and_capture_bytes(_completed_status_event())

    parsed = consumer._parse_msg(FakeConsumerRecord(published_bytes))

    assert parsed == _completed_status_event()


def test_consumer_rejects_a_message_that_is_not_a_progress_envelope() -> None:
    """Verify garbage on the topic raises the consumer's own parse error."""
    consumer = ReviewProgressConsumer(RecordingBroadcaster())

    with pytest.raises(ReviewProgressMessageParseError):
        consumer._parse_msg(FakeConsumerRecord(b'{"kind": "unknown"}'))


@pytest.mark.asyncio
async def test_consumer_hands_each_event_to_the_local_broadcaster() -> None:
    """Verify an event that arrives from Kafka reaches this replica's SSE subscribers."""
    broadcaster = RecordingBroadcaster()
    consumer = ReviewProgressConsumer(broadcaster)
    published_bytes = await _publish_and_capture_bytes(_file_event())

    await consumer._process_message(FakeConsumerRecord(published_bytes), FakeKafkaConsumer())

    assert broadcaster.received == [(REVIEW_ID, _file_event())]


def test_each_consumer_instance_joins_its_own_group() -> None:
    """Verify replicas never share a group, since a shared group would split events between them."""
    first = ReviewProgressConsumer(RecordingBroadcaster())
    second = ReviewProgressConsumer(RecordingBroadcaster())

    assert first.group_id != second.group_id


def test_consumer_starts_from_the_latest_offset() -> None:
    """Verify a replica starting up relays live events rather than replaying old reviews."""
    consumer = ReviewProgressConsumer(RecordingBroadcaster())

    assert consumer.auto_offset_reset == "latest"
