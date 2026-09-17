"""
    Tests for RepoIndexDlqConsumer against fakes: no real Kafka broker, no real notifier.
"""
import pytest

from api.indexing.consumers.dlq_consumer import RepoIndexDlqConsumer
from api.schemas.indexing import RepoRegisteredMessage


class FakeConsumerRecord:
    def __init__(self, value: bytes, headers: list[tuple[str, bytes]] | None = None, offset: int = 0) -> None:
        self.value = value
        self.headers = headers or []
        self.offset = offset


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

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
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


def _make_message(**overrides) -> RepoRegisteredMessage:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "registered_by_user_id": 1,
    }
    defaults.update(overrides)
    return RepoRegisteredMessage(**defaults)


@pytest.mark.asyncio
async def test_process_message_notifies_with_repo_id_and_error_headers_then_commits() -> None:
    notifier = FakeNotifier()
    consumer = RepoIndexDlqConsumer(notifier)
    message = _make_message(repo_id=10)
    record = FakeConsumerRecord(
        value=message.model_dump_json().encode(),
        headers=[("error_type", b"RuntimeError"), ("error_message", b"github unreachable")],
    )
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    [(subject, body)] = notifier.sent
    assert "repo_id=10" in subject
    assert "RuntimeError" in subject
    assert "github unreachable" in body
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_falls_back_to_unknown_repo_id_for_unparseable_payload() -> None:
    notifier = FakeNotifier()
    consumer = RepoIndexDlqConsumer(notifier)
    record = FakeConsumerRecord(value=b"not-json-at-all", headers=[])
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    [(subject, _body)] = notifier.sent
    assert "repo_id=unknown" in subject
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_commits_even_when_notifier_raises() -> None:
    notifier = FakeNotifier(notify_error=RuntimeError("sns down"))
    consumer = RepoIndexDlqConsumer(notifier)
    message = _make_message(repo_id=10)
    record = FakeConsumerRecord(value=message.model_dump_json().encode())
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_consume_starts_stops_and_notifies_for_every_message() -> None:
    notifier = FakeNotifier()
    consumer = RepoIndexDlqConsumer(notifier)
    messages = [
        FakeConsumerRecord(value=_make_message(repo_id=1).model_dump_json().encode()),
        FakeConsumerRecord(value=_make_message(repo_id=2).model_dump_json().encode()),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert len(notifier.sent) == 2
    assert kafka_consumer.commit_count == 2
