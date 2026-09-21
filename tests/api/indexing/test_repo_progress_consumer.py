"""
    Tests for RepoProgressConsumer against fakes: no real Kafka broker, no real broadcaster wiring.
"""
import pytest

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus
from api.indexing.consumers.repo_progress_consumer import (
    RepoProgressConsumer,
    RepoProgressConsumerDependencies,
    RepoProgressMessageParseError,
)
from api.indexing.repo_progress_broadcaster import ProgressEvent
from api.indexing.topics import REPO_FILE_PROGRESS, REPO_STATUS_PROGRESS
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage


class FakeConsumerRecord:
    def __init__(self, value: bytes, topic: str, offset: int = 0) -> None:
        self.value = value
        self.topic = topic
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


class FakeBroadcaster:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[int, ProgressEvent]] = []

    async def publish(self, repo_id: int, event: ProgressEvent) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((repo_id, event))


def _file_progress_message(**overrides) -> RepoFileProgressMessage:
    defaults = {"repo_id": 10, "file_path": "main.py", "status": IndexedFileStatus.INDEXED, "status_reason": None}
    defaults.update(overrides)
    return RepoFileProgressMessage(**defaults)


def _status_progress_message(**overrides) -> RepoStatusProgressMessage:
    defaults = {"repo_id": 10, "status": RepoIndexStatus.COMPLETED, "status_reason": None}
    defaults.update(overrides)
    return RepoStatusProgressMessage(**defaults)


def _make_consumer(*, broadcaster: FakeBroadcaster | None = None) -> tuple[RepoProgressConsumer, FakeBroadcaster]:
    broadcaster = broadcaster or FakeBroadcaster()
    dependencies = RepoProgressConsumerDependencies(broadcaster=broadcaster)
    return RepoProgressConsumer(dependencies, group_id="test-group"), broadcaster


@pytest.mark.asyncio
async def test_process_message_broadcasts_a_file_progress_event() -> None:
    consumer, broadcaster = _make_consumer()
    message = _file_progress_message()
    record = FakeConsumerRecord(value=message.model_dump_json().encode(), topic=REPO_FILE_PROGRESS)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    [(repo_id, event)] = broadcaster.published
    assert repo_id == 10
    assert event == message
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_broadcasts_a_status_progress_event() -> None:
    consumer, broadcaster = _make_consumer()
    message = _status_progress_message()
    record = FakeConsumerRecord(value=message.model_dump_json().encode(), topic=REPO_STATUS_PROGRESS)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    [(repo_id, event)] = broadcaster.published
    assert repo_id == 10
    assert event == message
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_logs_and_commits_on_unparseable_payload() -> None:
    consumer, broadcaster = _make_consumer()
    record = FakeConsumerRecord(value=b"not-json-at-all", topic=REPO_FILE_PROGRESS)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    assert broadcaster.published == []
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_logs_and_commits_for_an_unexpected_topic() -> None:
    consumer, broadcaster = _make_consumer()
    message = _file_progress_message()
    record = FakeConsumerRecord(value=message.model_dump_json().encode(), topic="some.other.topic")
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    assert broadcaster.published == []
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_commits_even_when_broadcast_raises() -> None:
    broadcaster = FakeBroadcaster(publish_error=RuntimeError("boom"))
    consumer, _broadcaster = _make_consumer(broadcaster=broadcaster)
    message = _file_progress_message()
    record = FakeConsumerRecord(value=message.model_dump_json().encode(), topic=REPO_FILE_PROGRESS)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(record, kafka_consumer)

    assert kafka_consumer.commit_count == 1


def test_parse_msg_raises_repo_progress_message_parse_error_for_bad_json() -> None:
    consumer, _broadcaster = _make_consumer()
    record = FakeConsumerRecord(value=b"not-json-at-all", topic=REPO_FILE_PROGRESS)

    with pytest.raises(RepoProgressMessageParseError):
        consumer._parse_msg(record)


@pytest.mark.asyncio
async def test_consume_starts_stops_and_processes_every_message() -> None:
    consumer, broadcaster = _make_consumer()
    messages = [
        FakeConsumerRecord(value=_file_progress_message(file_path="a.py").model_dump_json().encode(), topic=REPO_FILE_PROGRESS),
        FakeConsumerRecord(value=_status_progress_message().model_dump_json().encode(), topic=REPO_STATUS_PROGRESS),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert len(broadcaster.published) == 2
    assert kafka_consumer.commit_count == 2


def test_group_id_defaults_to_a_unique_value_per_instance() -> None:
    dependencies = RepoProgressConsumerDependencies(broadcaster=FakeBroadcaster())

    first_consumer = RepoProgressConsumer(dependencies)
    second_consumer = RepoProgressConsumer(dependencies)

    assert first_consumer.group_id != second_consumer.group_id
