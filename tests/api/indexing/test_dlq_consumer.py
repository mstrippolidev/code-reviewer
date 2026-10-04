"""
    Tests for DlqConsumer against fakes: no real Kafka broker, no real notifier.
"""
from collections.abc import AsyncIterator

import pytest

from api.indexing.consumers.dlq_consumer import TOPICS, DlqConsumer
from api.indexing.topics import REPO_FILE_INDEX_DLQ, REPO_REGISTERED_DLQ
from api.review.topics import REVIEW_REQUESTED_DLQ


class FakeConsumerRecord:
    def __init__(
        self,
        topic: str = REPO_REGISTERED_DLQ,
        key: bytes | None = b"10",
        headers: list[tuple[str, bytes]] | None = None,
        offset: int = 0,
    ) -> None:
        self.topic = topic
        self.partition = 1
        self.offset = offset
        self.key = key
        self.value = b'{"private": "payload"}'
        self.headers = headers or []


class FakeKafkaConsumer:
    def __init__(self, messages: list[FakeConsumerRecord]) -> None:
        self._messages = messages
        self.started = False
        self.stopped = False
        self.commit_count = 0

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def commit(self) -> None:
        self.commit_count += 1

    def __aiter__(self) -> AsyncIterator[FakeConsumerRecord]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[FakeConsumerRecord]:
        for message in self._messages:
            yield message


class FakeNotifier:
    def __init__(self, *, notify_error: Exception | None = None) -> None:
        self._notify_error = notify_error
        self.sent: list[tuple[str, str]] = []

    def notify(self, subject: str, body: str) -> None:
        if self._notify_error:
            raise self._notify_error
        self.sent.append((subject, body))


def _error_headers() -> list[tuple[str, bytes]]:
    return [("error_type", b"RuntimeError"), ("error_message", b"github unreachable")]


def test_consumer_subscribes_to_every_dead_letter_topic() -> None:
    """Verify no DLQ topic can receive messages that nobody is told about."""
    consumer = DlqConsumer(FakeNotifier())

    assert set(consumer.topic) == {REPO_REGISTERED_DLQ, REPO_FILE_INDEX_DLQ, REVIEW_REQUESTED_DLQ}


def test_consumer_topics_are_all_dead_letter_topics() -> None:
    """Verify the subscription list only holds topics ending in .dlq."""
    assert all(topic.endswith(".dlq") for topic in TOPICS)


@pytest.mark.asyncio
async def test_process_message_puts_topic_and_error_type_in_subject() -> None:
    """Verify the subject alone tells which pipeline failed and how."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    record = FakeConsumerRecord(topic=REVIEW_REQUESTED_DLQ, headers=_error_headers())

    await consumer._process_message(record, FakeKafkaConsumer([]))

    [(subject, _body)] = notifier.sent
    assert subject == "review.requested.dlq: RuntimeError"


@pytest.mark.asyncio
async def test_process_message_puts_error_message_and_key_in_body() -> None:
    """Verify the body carries what is needed to find and diagnose the message."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    record = FakeConsumerRecord(key=b"10", headers=_error_headers())

    await consumer._process_message(record, FakeKafkaConsumer([]))

    [(_subject, body)] = notifier.sent
    assert "github unreachable" in body
    assert "key: 10" in body


@pytest.mark.asyncio
async def test_process_message_never_includes_the_message_payload() -> None:
    """Verify a private repo's content cannot leak into an email through the payload."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    record = FakeConsumerRecord(headers=_error_headers())

    await consumer._process_message(record, FakeKafkaConsumer([]))

    [(_subject, body)] = notifier.sent
    assert "private" not in body


@pytest.mark.asyncio
async def test_process_message_without_error_headers_reports_unknown_error() -> None:
    """Verify a message dead-lettered without headers still produces a notification."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    record = FakeConsumerRecord(headers=[])

    await consumer._process_message(record, FakeKafkaConsumer([]))

    [(subject, _body)] = notifier.sent
    assert subject == "repo.registered.dlq: UnknownError"


@pytest.mark.asyncio
async def test_process_message_without_key_reports_none() -> None:
    """Verify a keyless message does not crash the notification."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    record = FakeConsumerRecord(key=None)

    await consumer._process_message(record, FakeKafkaConsumer([]))

    [(_subject, body)] = notifier.sent
    assert "key: none" in body


@pytest.mark.asyncio
async def test_process_message_commits_after_notifying() -> None:
    """Verify the offset advances once the notification is sent."""
    consumer = DlqConsumer(FakeNotifier())
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(), kafka_consumer)

    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_commits_even_when_notifier_raises() -> None:
    """Verify a down SNS cannot wedge the consumer group on one message."""
    consumer = DlqConsumer(FakeNotifier(notify_error=RuntimeError("sns down")))
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(), kafka_consumer)

    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_consume_notifies_once_per_message_and_stops_cleanly() -> None:
    """Verify the loop sends one notification per dead letter, across topics."""
    notifier = FakeNotifier()
    consumer = DlqConsumer(notifier)
    kafka_consumer = FakeKafkaConsumer(
        [FakeConsumerRecord(topic=REPO_REGISTERED_DLQ), FakeConsumerRecord(topic=REVIEW_REQUESTED_DLQ)]
    )
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert len(notifier.sent) == 2
    assert kafka_consumer.stopped is True
