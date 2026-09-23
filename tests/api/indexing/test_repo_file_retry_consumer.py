"""
    Tests for RepoFileRetryConsumer against fakes: no real Kafka broker, no real RepoIndexer.
"""
import pytest

from api.indexing.consumers.repo_file_retry_consumer import (
    RepoFileRetryConsumer,
    RepoFileRetryConsumerDependencies,
    RepoFileRetryMessageParseError,
)
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
        self.retried_repo_ids: list[int] = []

    async def retry_failed_files(self, repo_msg: RepoRegisteredMessage) -> None:
        error = self._error_by_repo_id.get(repo_msg.repo_id)
        if error:
            raise error
        self.retried_repo_ids.append(repo_msg.repo_id)


def _make_message(**overrides) -> RepoRegisteredMessage:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "branch": "main",
        "registered_by_user_id": 1,
    }
    defaults.update(overrides)
    return RepoRegisteredMessage(**defaults)


def _make_consumer(*, indexer: FakeIndexer) -> RepoFileRetryConsumer:
    placeholder_indexer_dependencies = RepoIndexerDependencies(
        database_engine=None,
        http_client=None,
        token_cipher=None,
        github_client=None,
        repo_producer=None,
        completion_finalizer=None,
        max_concurrent_file_dispatch=8,
    )
    dependencies = RepoFileRetryConsumerDependencies(indexer_dependencies=placeholder_indexer_dependencies)
    consumer = RepoFileRetryConsumer(dependencies)
    consumer._indexer = indexer
    return consumer


@pytest.mark.asyncio
async def test_process_message_retries_successfully_and_commits() -> None:
    indexer = FakeIndexer()
    consumer = _make_consumer(indexer=indexer)
    message = _make_message(repo_id=10)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert indexer.retried_repo_ids == [10]
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_logs_and_commits_on_an_unparseable_payload() -> None:
    indexer = FakeIndexer()
    consumer = _make_consumer(indexer=indexer)
    kafka_consumer = FakeKafkaConsumer([])
    bad_payload = b"not-json-at-all"

    await consumer._process_message(FakeConsumerRecord(value=bad_payload), kafka_consumer)

    assert indexer.retried_repo_ids == []
    assert kafka_consumer.commit_count == 1


def test_parse_msg_raises_repo_file_retry_message_parse_error_on_bad_json() -> None:
    consumer = _make_consumer(indexer=FakeIndexer())

    with pytest.raises(RepoFileRetryMessageParseError):
        consumer._parse_msg(FakeConsumerRecord(value=b"not-json-at-all"))


@pytest.mark.asyncio
async def test_process_message_logs_and_commits_when_retry_raises() -> None:
    indexer = FakeIndexer(error_by_repo_id={10: RuntimeError("github unreachable")})
    consumer = _make_consumer(indexer=indexer)
    message = _make_message(repo_id=10)
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert indexer.retried_repo_ids == []
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_consume_starts_stops_and_processes_every_message() -> None:
    indexer = FakeIndexer()
    consumer = _make_consumer(indexer=indexer)
    messages = [
        FakeConsumerRecord(value=_make_message(repo_id=1).model_dump_json().encode()),
        FakeConsumerRecord(value=_make_message(repo_id=2).model_dump_json().encode()),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert indexer.retried_repo_ids == [1, 2]
    assert kafka_consumer.commit_count == 2
