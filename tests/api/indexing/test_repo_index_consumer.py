"""
    Tests for RepoIndexConsumer against fakes: no real Kafka broker, no real RepoIndexer.
"""
import pytest

from api.indexing.consumers.repo_index_consumer import (
    RepoIndexConsumer,
    RepoIndexConsumerDependencies,
    RepoRegisteredMessageParseError,
)
from api.indexing.producer import DlqPublishError
from api.indexing.repo_indexer import RepoIndexerDependencies
from api.schemas.indexing import RepoRegisteredMessage


class FakeConsumerRecord:
    def __init__(self, value: bytes, key: bytes | None = None, offset: int = 0) -> None:
        self.value = value
        self.key = key
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


class FakeIndexer:
    def __init__(self, *, error_by_repo_id: dict[int, Exception] | None = None) -> None:
        self._error_by_repo_id = error_by_repo_id or {}
        self.indexed_repo_ids: list[int] = []

    async def index_repo(self, repo_msg: RepoRegisteredMessage) -> None:
        error = self._error_by_repo_id.get(repo_msg.repo_id)
        if error:
            raise error
        self.indexed_repo_ids.append(repo_msg.repo_id)


class FakeDlqProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[str, bytes, bytes | None, Exception]] = []

    async def publish_to_dlq(self, dlq_topic: str, payload: bytes, key: bytes | None, error: Exception) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((dlq_topic, payload, key, error))


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


def _make_consumer(*, indexer: FakeIndexer, dlq_producer: FakeDlqProducer) -> RepoIndexConsumer:
    placeholder_indexer_dependencies = RepoIndexerDependencies(
        database_engine=None, http_client=None, token_cipher=None, github_client=None, rag_manager=None
    )
    dependencies = RepoIndexConsumerDependencies(
        indexer_dependencies=placeholder_indexer_dependencies, dlq_producer=dlq_producer
    )
    consumer = RepoIndexConsumer(dependencies)
    consumer._indexer = indexer
    return consumer


@pytest.mark.asyncio
async def test_process_message_indexes_successfully_and_commits() -> None:
    indexer = FakeIndexer()
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    message = _make_message(repo_id=10)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert indexer.indexed_repo_ids == [10]
    assert dlq_producer.published == []
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_sends_unparseable_payload_to_dlq_and_commits() -> None:
    indexer = FakeIndexer()
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    kafka_consumer = FakeKafkaConsumer([])
    bad_payload = b"not-json-at-all"

    await consumer._process_message(FakeConsumerRecord(value=bad_payload, key=b"10"), kafka_consumer)

    assert indexer.indexed_repo_ids == []
    [(dlq_topic, payload, key, error)] = dlq_producer.published
    assert dlq_topic
    assert payload == bad_payload
    assert key == b"10"
    assert isinstance(error, RepoRegisteredMessageParseError)
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_sends_an_indexing_failure_to_dlq_and_commits() -> None:
    indexing_error = RuntimeError("github unreachable")
    indexer = FakeIndexer(error_by_repo_id={10: indexing_error})
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    message = _make_message(repo_id=10)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(
        FakeConsumerRecord(value=message.model_dump_json().encode(), key=b"10"), kafka_consumer
    )

    [(_topic, _payload, _key, error)] = dlq_producer.published
    assert error is indexing_error
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_raises_and_does_not_commit_when_dlq_publish_also_fails() -> None:
    indexer = FakeIndexer(error_by_repo_id={10: RuntimeError("github unreachable")})
    dlq_producer = FakeDlqProducer(publish_error=DlqPublishError("broker also down"))
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    message = _make_message(repo_id=10)
    kafka_consumer = FakeKafkaConsumer([])

    with pytest.raises(DlqPublishError):
        await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert kafka_consumer.commit_count == 0


@pytest.mark.asyncio
async def test_consume_starts_stops_and_processes_every_message() -> None:
    indexer = FakeIndexer()
    dlq_producer = FakeDlqProducer()
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    messages = [
        FakeConsumerRecord(value=_make_message(repo_id=1).model_dump_json().encode()),
        FakeConsumerRecord(value=_make_message(repo_id=2).model_dump_json().encode()),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert indexer.indexed_repo_ids == [1, 2]
    assert kafka_consumer.commit_count == 2


@pytest.mark.asyncio
async def test_consume_stops_the_kafka_client_and_propagates_when_dlq_also_fails() -> None:
    indexer = FakeIndexer(error_by_repo_id={1: RuntimeError("boom")})
    dlq_producer = FakeDlqProducer(publish_error=DlqPublishError("dlq also down"))
    consumer = _make_consumer(indexer=indexer, dlq_producer=dlq_producer)
    messages = [
        FakeConsumerRecord(value=_make_message(repo_id=1).model_dump_json().encode()),
        FakeConsumerRecord(value=_make_message(repo_id=2).model_dump_json().encode()),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    with pytest.raises(DlqPublishError):
        await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert indexer.indexed_repo_ids == []
    assert kafka_consumer.commit_count == 0
