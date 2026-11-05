"""
    Tests that ConsumerInterface reports every message it handles, how long it took, and a crashed loop.
    The Kafka consumer is a fake.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.indexing.consumers import interface
from api.indexing.consumers.interface import ConsumerInterface
from api.observability.kafka_metrics import KafkaMetrics
from tests.metric_points import (
    KAFKA_CONSUMER_CRASHES,
    KAFKA_CONSUMER_MESSAGES,
    KAFKA_HANDLER_DURATION,
    point_with,
    points_for,
)

TOPIC = "review.requested"
_CONSUMER = "code_reviewer.consumer"
_OUTCOME = "code_reviewer.outcome"


class FakeConsumerRecord:
    def __init__(self, value: bytes) -> None:
        self.topic = TOPIC
        self.headers: list[tuple[str, bytes]] = []
        self.value = value
        self.offset = 0


class FakeKafkaConsumer:
    def __init__(self, records: list[FakeConsumerRecord] | None = None, *, crash: bool = False) -> None:
        self._records = records or []
        self._crash = crash
        self.commit_count = 0

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def commit(self) -> None:
        self.commit_count += 1

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for record in self._records:
            yield record
        if self._crash:
            raise RuntimeError("coordinator lost")


class ParsingConsumer(ConsumerInterface[bytes]):
    def __init__(self, fake: FakeKafkaConsumer | None = None, *, handler_error: Exception | None = None) -> None:
        super().__init__(TOPIC, "unused", "test_group")
        self._fake = fake or FakeKafkaConsumer()
        self._handler_error = handler_error

    def _build(self) -> FakeKafkaConsumer:
        return self._fake

    def _parse_msg(self, msg: FakeConsumerRecord) -> bytes:
        if msg.value == b"bad":
            raise ValueError("unparseable")
        return msg.value

    async def _handle_parse_error(self, msg: FakeConsumerRecord, error: Exception) -> None:
        return None

    async def _handle_parsed_message(self, parsed: bytes, msg: FakeConsumerRecord, consumer: FakeKafkaConsumer) -> None:
        if self._handler_error:
            raise self._handler_error


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_kafka_metrics: KafkaMetrics) -> None:
    """Points the consumer base class at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(interface, "kafka_metrics", isolated_kafka_metrics)


@pytest.mark.asyncio
async def test_a_handled_message_is_counted_as_processed(metric_reader: InMemoryMetricReader) -> None:
    """Verify a message that parsed, was handled and committed counts as processed under its consumer's name."""
    await ParsingConsumer()._process_message(FakeConsumerRecord(b"ok"), FakeKafkaConsumer())

    point = point_with(metric_reader, KAFKA_CONSUMER_MESSAGES, {_CONSUMER: "ParsingConsumer", _OUTCOME: "processed"})
    assert point.value == 1


@pytest.mark.asyncio
async def test_an_unparseable_message_is_counted_as_a_parse_error(metric_reader: InMemoryMetricReader) -> None:
    """Verify a message that cannot be parsed is its own outcome and is not also counted as processed."""
    await ParsingConsumer()._process_message(FakeConsumerRecord(b"bad"), FakeKafkaConsumer())

    assert point_with(metric_reader, KAFKA_CONSUMER_MESSAGES, {_OUTCOME: "parse_error"}).value == 1
    assert len(points_for(metric_reader, KAFKA_CONSUMER_MESSAGES)) == 1


@pytest.mark.asyncio
async def test_handling_time_is_recorded_for_every_message(metric_reader: InMemoryMetricReader) -> None:
    """Verify each message adds one point to the handler duration, whatever its outcome."""
    consumer = ParsingConsumer()

    await consumer._process_message(FakeConsumerRecord(b"ok"), FakeKafkaConsumer())
    await consumer._process_message(FakeConsumerRecord(b"bad"), FakeKafkaConsumer())

    assert point_with(metric_reader, KAFKA_HANDLER_DURATION, {_CONSUMER: "ParsingConsumer"}).count == 2


@pytest.mark.asyncio
async def test_a_handler_that_raises_is_timed_but_not_counted_as_processed(metric_reader: InMemoryMetricReader) -> None:
    """Verify an unhandled handler error is not reported as a processed message, and the error still propagates."""
    consumer = ParsingConsumer(handler_error=RuntimeError("handler boom"))

    with pytest.raises(RuntimeError):
        await consumer._process_message(FakeConsumerRecord(b"ok"), FakeKafkaConsumer())

    assert point_with(metric_reader, KAFKA_HANDLER_DURATION, {_CONSUMER: "ParsingConsumer"}).count == 1
    assert points_for(metric_reader, KAFKA_CONSUMER_MESSAGES) == []


@pytest.mark.asyncio
async def test_a_crashed_consumer_loop_is_counted_once_and_still_raises(metric_reader: InMemoryMetricReader) -> None:
    """Verify an error that ends the loop adds one crash and propagates, so the task still dies loudly."""
    consumer = ParsingConsumer(FakeKafkaConsumer(crash=True))

    with pytest.raises(RuntimeError):
        await consumer.consume()

    assert point_with(metric_reader, KAFKA_CONSUMER_CRASHES, {_CONSUMER: "ParsingConsumer"}).value == 1


@pytest.mark.asyncio
async def test_a_consumer_loop_that_ends_normally_records_no_crash(metric_reader: InMemoryMetricReader) -> None:
    """Verify a loop that drains its messages and stops is not counted as a crash."""
    fake = FakeKafkaConsumer([FakeConsumerRecord(b"ok")])

    await ParsingConsumer(fake).consume()

    assert points_for(metric_reader, KAFKA_CONSUMER_CRASHES) == []
    assert fake.commit_count == 1
