"""
    Tests for RepoIndexProducer against a fake underlying AIOKafkaProducer: no real Kafka broker.
"""
from unittest.mock import AsyncMock

import pytest
from aiokafka.errors import KafkaError

from api.indexing.producer import RepoIndexProducer, RepoRegisteredPublishError
from api.schemas.indexing import RepoRegisteredMessage


class _FakeRecordMetadata:
    def __init__(self, partition: int, offset: int) -> None:
        self.partition = partition
        self.offset = offset


class FakeAIOKafkaProducer:
    def __init__(self, *, send_error: Exception | None = None, fail_count: int | None = None) -> None:
        self._send_error = send_error
        self._fail_count = fail_count
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, bytes, bytes]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(
        self, topic: str, value: bytes, key: bytes, headers: list[tuple[str, bytes]] | None = None
    ) -> _FakeRecordMetadata:
        if self._send_error and (self._fail_count is None or self._fail_count > 0):
            if self._fail_count is not None:
                self._fail_count -= 1
            raise self._send_error
        self.sent.append((topic, value, key))
        return _FakeRecordMetadata(partition=1, offset=42)


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
async def test_start_delegates_to_the_underlying_producer() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    await producer.start()

    assert fake.started is True


@pytest.mark.asyncio
async def test_stop_delegates_to_the_underlying_producer() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    await producer.stop()

    assert fake.stopped is True


@pytest.mark.asyncio
async def test_publish_repo_registered_sends_to_the_configured_topic() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    await producer.publish_repo_registered(_make_message())

    [(topic, _value, _key)] = fake.sent
    assert topic == "repo.registered"


@pytest.mark.asyncio
async def test_publish_repo_registered_keys_the_message_by_repo_id() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    await producer.publish_repo_registered(_make_message(repo_id=10))

    [(_topic, _value, key)] = fake.sent
    assert key == b"10"


@pytest.mark.asyncio
async def test_publish_repo_registered_sends_the_message_as_json() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)
    message = _make_message()

    await producer.publish_repo_registered(message)

    [(_topic, value, _key)] = fake.sent
    assert RepoRegisteredMessage.model_validate_json(value) == message


@pytest.mark.asyncio
async def test_publish_repo_registered_wraps_a_kafka_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.indexing.producer.asyncio.sleep", AsyncMock())
    fake = FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable"))
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    with pytest.raises(RepoRegisteredPublishError):
        await producer.publish_repo_registered(_make_message())


@pytest.mark.asyncio
async def test_publish_repo_registered_retries_a_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("api.indexing.producer.asyncio.sleep", AsyncMock())
    fake = FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable"), fail_count=1)
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", topic="repo.registered", producer=fake)

    await producer.publish_repo_registered(_make_message())

    [(_topic, _value, _key)] = fake.sent
