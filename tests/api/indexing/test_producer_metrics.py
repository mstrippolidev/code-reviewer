"""
    Tests that RepoIndexProducer reports every publish and every dead-letter publish, including the failures
    its callers swallow. The underlying Kafka producer is a fake.
"""
import pytest
from aiokafka.errors import KafkaError
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.indexing import producer as producer_module
from api.indexing.producer import DlqPublishError, PublishError, RepoIndexProducer
from api.observability.kafka_metrics import KafkaMetrics
from tests.api.indexing.test_producer import FakeAIOKafkaProducer, _make_message
from tests.metric_points import KAFKA_DLQ_MESSAGES, KAFKA_PRODUCER_MESSAGES, point_with

_TOPIC = "code_reviewer.topic"
_OUTCOME = "code_reviewer.outcome"
_ERROR_TYPE = "code_reviewer.error_type"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_kafka_metrics: KafkaMetrics) -> None:
    """Points the producer at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(producer_module, "kafka_metrics", isolated_kafka_metrics)


def _producer(fake: FakeAIOKafkaProducer) -> RepoIndexProducer:
    return RepoIndexProducer(bootstrap_servers="localhost:30092", producer=fake)


@pytest.mark.asyncio
async def test_a_published_message_is_counted(metric_reader: InMemoryMetricReader) -> None:
    """Verify a successful publish adds one to its topic's published series."""
    await _producer(FakeAIOKafkaProducer()).publish("repo.registered", _make_message(), b"10")

    point = point_with(metric_reader, KAFKA_PRODUCER_MESSAGES, {_TOPIC: "repo.registered", _OUTCOME: "published"})
    assert point.value == 1


@pytest.mark.asyncio
async def test_a_failed_publish_is_counted_and_still_raises(metric_reader: InMemoryMetricReader) -> None:
    """Verify the failure callers go on to swallow is visible in the metric, and the error still propagates."""
    producer = _producer(FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable")))

    with pytest.raises(PublishError):
        await producer.publish("repo.registered", _make_message(), b"10")

    point = point_with(metric_reader, KAFKA_PRODUCER_MESSAGES, {_TOPIC: "repo.registered", _OUTCOME: "failed"})
    assert point.value == 1


@pytest.mark.asyncio
async def test_a_dead_letter_is_counted_with_the_error_type(metric_reader: InMemoryMetricReader) -> None:
    """Verify a forwarded dead letter is counted under the class name of the error that caused it."""
    await _producer(FakeAIOKafkaProducer()).publish_to_dlq("repo.registered.dlq", b"payload", b"10", ValueError("boom"))

    point = point_with(
        metric_reader,
        KAFKA_DLQ_MESSAGES,
        {_TOPIC: "repo.registered.dlq", _ERROR_TYPE: "ValueError", _OUTCOME: "published"},
    )
    assert point.value == 1


@pytest.mark.asyncio
async def test_a_dead_letter_that_could_not_be_sent_is_counted_and_still_raises(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify a message lost on its way to the DLQ is counted as failed, and the error still propagates."""
    producer = _producer(FakeAIOKafkaProducer(send_error=KafkaError("broker unreachable")))

    with pytest.raises(DlqPublishError):
        await producer.publish_to_dlq("repo.registered.dlq", b"payload", b"10", ValueError("boom"))

    point = point_with(metric_reader, KAFKA_DLQ_MESSAGES, {_TOPIC: "repo.registered.dlq", _OUTCOME: "failed"})
    assert point.value == 1
