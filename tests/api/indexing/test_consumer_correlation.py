"""
    ConsumerInterface stamps the ids a parsed message carries on the log lines of its handler.
"""
import logging
from uuid import UUID

import pytest
from pydantic import BaseModel

from api.indexing.consumers.interface import ConsumerInterface
from api.observability.correlation import CorrelationFilter

TOPIC = "review.requested"
REVIEW_ID = UUID("0af76519-16cd-43dd-8448-eb211c80319c")


class ReviewLikeMessage(BaseModel):
    review_id: UUID
    repo_id: int | None = None
    owner_id: int | None = None
    content: str = "not an id"


class SearchLikeMessage(BaseModel):
    search_id: UUID
    repo_id: int


class FakeConsumerRecord:
    def __init__(self, value: bytes) -> None:
        self.topic = TOPIC
        self.headers: list[tuple[str, bytes]] = []
        self.value = value
        self.offset = 0


class FakeKafkaConsumer:
    async def commit(self) -> None:
        pass


class RecordingConsumer(ConsumerInterface[BaseModel]):
    def __init__(self, message: BaseModel) -> None:
        super().__init__(TOPIC, "unused")
        self._message = message
        self.correlation_while_handling: str | None = None

    def _parse_msg(self, msg: FakeConsumerRecord) -> BaseModel:
        return self._message

    async def _handle_parse_error(self, msg: FakeConsumerRecord, error: Exception) -> None:
        raise error

    async def _handle_parsed_message(
        self, parsed: BaseModel, msg: FakeConsumerRecord, consumer: FakeKafkaConsumer
    ) -> None:
        self.correlation_while_handling = _current_correlation()


def _current_correlation() -> str:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
    CorrelationFilter().filter(record)
    return record.correlation


@pytest.mark.asyncio
async def test_handler_logs_carry_the_ids_of_the_message() -> None:
    """Verify review_id, repo_id and owner_id are on the line, and the message body is not."""
    consumer = RecordingConsumer(ReviewLikeMessage(review_id=REVIEW_ID, repo_id=7, owner_id=9))

    await consumer._process_message(FakeConsumerRecord(b""), FakeKafkaConsumer())

    assert consumer.correlation_while_handling == f"review_id={REVIEW_ID} repo_id=7 owner_id=9"


@pytest.mark.asyncio
async def test_a_message_with_other_ids_is_stamped_with_those() -> None:
    """Verify one default works for every message shape, with no per-consumer code."""
    consumer = RecordingConsumer(SearchLikeMessage(search_id=REVIEW_ID, repo_id=3))

    await consumer._process_message(FakeConsumerRecord(b""), FakeKafkaConsumer())

    assert consumer.correlation_while_handling == f"search_id={REVIEW_ID} repo_id=3"


@pytest.mark.asyncio
async def test_a_message_without_ids_leaves_the_line_unstamped() -> None:
    """Verify consumers whose messages carry no id (progress, dead letters) are unaffected."""
    consumer = RecordingConsumer(ReviewLikeMessage.model_construct(content="x"))

    await consumer._process_message(FakeConsumerRecord(b""), FakeKafkaConsumer())

    assert consumer.correlation_while_handling == ""


@pytest.mark.asyncio
async def test_ids_are_cleared_after_the_message_is_handled() -> None:
    """Verify the next message, and the consumer loop's own logs, do not inherit the ids."""
    consumer = RecordingConsumer(ReviewLikeMessage(review_id=REVIEW_ID, repo_id=7))

    await consumer._process_message(FakeConsumerRecord(b""), FakeKafkaConsumer())

    assert _current_correlation() == ""
