"""
    Tests for RepoIndexProducer against a fake underlying AIOKafkaProducer: no real Kafka broker.
"""
import pytest
from aiokafka.errors import KafkaError

from api.indexing.producer import DlqPublishError, PublishError, RepoIndexProducer
from api.schemas.indexing import RepoRegisteredMessage


class _FakeRecordMetadata:
    def __init__(self, partition: int, offset: int) -> None:
        self.partition = partition
        self.offset = offset


class FakeAIOKafkaProducer:
    def __init__(self, *, send_error: Exception | None = None) -> None:
        self._send_error = send_error
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, bytes, bytes | None, list[tuple[str, bytes]] | None]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(
        self, topic: str, value: bytes, key: bytes | None, headers: list[tuple[str, bytes]] | None = None
    ) -> _FakeRecordMetadata:
        if self._send_error:
            raise self._send_error
        self.sent.append((topic, value, key, headers))
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
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    await producer.start()

    assert fake.started is True


@pytest.mark.asyncio
async def test_stop_delegates_to_the_underlying_producer() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    await producer.stop()

    assert fake.stopped is True


@pytest.mark.asyncio
async def test_publish_sends_to_the_given_topic() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    await producer.publish("repo.registered", _make_message(), b"10")

    [(topic, _value, _key, _headers)] = fake.sent
    assert topic == "repo.registered"


@pytest.mark.asyncio
async def test_publish_keys_the_message_as_given() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    await producer.publish("repo.registered", _make_message(repo_id=10), b"10")

    [(_topic, _value, key, _headers)] = fake.sent
    assert key == b"10"


@pytest.mark.asyncio
async def test_publish_sends_the_message_as_json() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)
    message = _make_message()

    await producer.publish("repo.registered", message, b"10")

    [(_topic, value, _key, _headers)] = fake.sent
    assert RepoRegisteredMessage.model_validate_json(value) == message


@pytest.mark.asyncio
async def test_publish_wraps_a_kafka_failure() -> None:
    fake = FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable"))
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    with pytest.raises(PublishError):
        await producer.publish("repo.registered", _make_message(), b"10")


@pytest.mark.asyncio
async def test_publish_to_dlq_sends_error_headers() -> None:
    fake = FakeAIOKafkaProducer()
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    await producer.publish_to_dlq("repo.registered.dlq", b"payload", b"10", ValueError("boom"))

    [(topic, value, key, headers)] = fake.sent
    assert topic == "repo.registered.dlq"
    assert value == b"payload"
    assert key == b"10"
    assert dict(headers) == {"error_type": b"ValueError", "error_message": b"boom"}


@pytest.mark.asyncio
async def test_publish_to_dlq_wraps_a_kafka_failure() -> None:
    fake = FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable"))
    producer = RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)

    with pytest.raises(DlqPublishError):
        await producer.publish_to_dlq("repo.registered.dlq", b"payload", b"10", ValueError("boom"))
