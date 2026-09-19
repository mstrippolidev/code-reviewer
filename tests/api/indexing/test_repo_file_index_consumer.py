"""
    Tests for RepoFileIndexConsumer against fakes: no real Kafka broker, no real DB,
    no real embedding model.
"""
import asyncio
import threading
import time

import pytest

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.indexing.consumers.repo_file_index_consumer import (
    RepoFileIndexConsumer,
    RepoFileIndexConsumerDependencies,
    RepoFileIndexMessageParseError,
)
from api.indexing.topics import REPO_FILE_INDEX_DLQ, REPO_FILE_PROGRESS
from api.schemas.indexing import RepoFileIndexMessage
from api.schemas.repos import RepoFileProgressMessage
from code_reviewer.rag.repo_data import RepoData


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


class FakeAsyncSession:
    """One session per repo.file.index message, seeded with the single IndexedFile row it should find."""

    def __init__(self, *, indexed_file: IndexedFile | None) -> None:
        self.indexed_file = indexed_file
        self.commit_count = 0

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def scalar(self, _statement) -> IndexedFile | None:
        return self.indexed_file

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabaseEngine:
    """Hands out one pre-seeded session per new_session() call, in the order given."""

    def __init__(self, sessions: list[FakeAsyncSession]) -> None:
        self._sessions = iter(sessions)

    def new_session(self) -> FakeAsyncSession:
        return next(self._sessions)


class FakeRagManager:
    def __init__(self, *, fail_paths: frozenset[str] = frozenset()) -> None:
        self._fail_paths = fail_paths
        self.indexed: list[tuple[RepoData, str, str]] = []

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        if file_path in self._fail_paths:
            raise RuntimeError(f"embedding failed for {file_path}")
        self.indexed.append((repo_data, file_path, content))


class FakeRepoProducer:
    def __init__(self, *, dlq_publish_error: Exception | None = None) -> None:
        self._dlq_publish_error = dlq_publish_error
        self.published: list[tuple[str, object, bytes]] = []
        self.dlq_published: list[tuple[str, bytes, bytes | None, Exception]] = []

    async def publish(self, topic: str, message: object, key: bytes) -> None:
        self.published.append((topic, message, key))

    async def publish_to_dlq(self, dlq_topic: str, payload: bytes, key: bytes | None, error: Exception) -> None:
        if self._dlq_publish_error:
            raise self._dlq_publish_error
        self.dlq_published.append((dlq_topic, payload, key, error))

    @property
    def progress_messages(self) -> list[RepoFileProgressMessage]:
        return [message for topic, message, _ in self.published if topic == REPO_FILE_PROGRESS]


class FakeCompletionFinalizer:
    def __init__(self) -> None:
        self.finalize_calls: list[int] = []

    async def finalize_if_complete(self, repo_id: int, _session: FakeAsyncSession) -> None:
        self.finalize_calls.append(repo_id)


def _make_message(**overrides) -> RepoFileIndexMessage:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "commit_sha": "abc123",
        "file_path": "main.py",
        "content": "print('hi')",
    }
    defaults.update(overrides)
    return RepoFileIndexMessage(**defaults)


def _make_consumer(
    *,
    indexed_files: list[IndexedFile | None],
    rag_manager: FakeRagManager | None = None,
    repo_producer: FakeRepoProducer | None = None,
    completion_finalizer: FakeCompletionFinalizer | None = None,
    max_concurrent_file_indexing: int = 4,
) -> tuple[RepoFileIndexConsumer, FakeRagManager, FakeRepoProducer, FakeCompletionFinalizer]:
    rag = rag_manager or FakeRagManager()
    producer = repo_producer or FakeRepoProducer()
    finalizer = completion_finalizer or FakeCompletionFinalizer()
    sessions = [FakeAsyncSession(indexed_file=row) for row in indexed_files]
    dependencies = RepoFileIndexConsumerDependencies(
        database_engine=FakeDatabaseEngine(sessions),
        rag_manager=rag,
        repo_producer=producer,
        completion_finalizer=finalizer,
        max_concurrent_file_indexing=max_concurrent_file_indexing,
    )
    return RepoFileIndexConsumer(dependencies), rag, producer, finalizer


@pytest.mark.asyncio
async def test_process_message_indexes_successfully_marks_indexed_and_publishes_progress() -> None:
    indexed_file = IndexedFile(repo_id=10, file_path="main.py", status=IndexedFileStatus.PENDING)
    consumer, rag, producer, finalizer = _make_consumer(indexed_files=[indexed_file])
    message = _make_message()
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert indexed_file.status == IndexedFileStatus.INDEXED
    assert indexed_file.indexed_at is not None
    [(repo_data, file_path, content)] = rag.indexed
    assert repo_data == RepoData(repo_id="10", commit_sha="abc123", owner_id="99")
    assert file_path == "main.py"
    assert content == "print('hi')"
    [progress] = producer.progress_messages
    assert progress.status == IndexedFileStatus.INDEXED
    assert finalizer.finalize_calls == [10]
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_marks_failed_and_publishes_progress_when_embedding_raises() -> None:
    indexed_file = IndexedFile(repo_id=10, file_path="bad.py", status=IndexedFileStatus.PENDING)
    rag = FakeRagManager(fail_paths=frozenset({"bad.py"}))
    consumer, _, producer, finalizer = _make_consumer(indexed_files=[indexed_file], rag_manager=rag)
    message = _make_message(file_path="bad.py")
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert indexed_file.status == IndexedFileStatus.FAILED
    assert "embedding failed" in indexed_file.status_reason
    [progress] = producer.progress_messages
    assert progress.status == IndexedFileStatus.FAILED
    assert finalizer.finalize_calls == [10]
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_sends_unparseable_payload_to_dlq_and_commits() -> None:
    consumer, rag, producer, _finalizer = _make_consumer(indexed_files=[])
    kafka_consumer = FakeKafkaConsumer([])
    bad_payload = b"not-json-at-all"

    await consumer._process_message(FakeConsumerRecord(value=bad_payload, key=b"10:main.py"), kafka_consumer)

    assert rag.indexed == []
    [(dlq_topic, payload, key, error)] = producer.dlq_published
    assert dlq_topic == REPO_FILE_INDEX_DLQ
    assert payload == bad_payload
    assert key == b"10:main.py"
    assert isinstance(error, RepoFileIndexMessageParseError)
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_process_message_drops_message_when_no_indexed_file_row_exists() -> None:
    consumer, rag, producer, finalizer = _make_consumer(indexed_files=[None])
    message = _make_message()
    kafka_consumer = FakeKafkaConsumer([])

    await consumer._process_message(FakeConsumerRecord(value=message.model_dump_json().encode()), kafka_consumer)

    assert rag.indexed == []
    assert producer.progress_messages == []
    assert finalizer.finalize_calls == []
    assert kafka_consumer.commit_count == 1


@pytest.mark.asyncio
async def test_consume_starts_stops_and_processes_every_message() -> None:
    indexed_files = [
        IndexedFile(repo_id=10, file_path="a.py", status=IndexedFileStatus.PENDING),
        IndexedFile(repo_id=10, file_path="b.py", status=IndexedFileStatus.PENDING),
    ]
    consumer, rag, _producer, _finalizer = _make_consumer(indexed_files=indexed_files)
    messages = [
        FakeConsumerRecord(value=_make_message(file_path="a.py").model_dump_json().encode()),
        FakeConsumerRecord(value=_make_message(file_path="b.py").model_dump_json().encode()),
    ]
    kafka_consumer = FakeKafkaConsumer(messages)
    consumer._build = lambda: kafka_consumer

    await consumer.consume()

    assert kafka_consumer.started is True
    assert kafka_consumer.stopped is True
    assert {file_path for _, file_path, _ in rag.indexed} == {"a.py", "b.py"}
    assert kafka_consumer.commit_count == 2


@pytest.mark.asyncio
async def test_semaphore_caps_concurrent_embedding_calls() -> None:
    """index_file is synchronous and runs via asyncio.to_thread; the semaphore around that
    call is what actually bounds how many run at once. This proves the cap holds under real
    concurrent scheduling, not just that the code compiles."""
    concurrent_calls = 0
    peak_concurrent_calls = 0
    lock = threading.Lock()

    class SlowRagManager:
        def index_file(self, _repo_data: RepoData, _file_path: str, _content: str) -> None:
            nonlocal concurrent_calls, peak_concurrent_calls
            with lock:
                concurrent_calls += 1
                peak_concurrent_calls = max(peak_concurrent_calls, concurrent_calls)
            time.sleep(0.05)
            with lock:
                concurrent_calls -= 1

    file_paths = [f"file_{i}.py" for i in range(4)]
    indexed_files = [IndexedFile(repo_id=10, file_path=path, status=IndexedFileStatus.PENDING) for path in file_paths]
    consumer, _rag, _producer, _finalizer = _make_consumer(
        indexed_files=indexed_files, rag_manager=SlowRagManager(), max_concurrent_file_indexing=2
    )
    messages = [_make_message(file_path=path) for path in file_paths]

    await asyncio.gather(*(consumer._index_file(message) for message in messages))

    assert peak_concurrent_calls == 2
