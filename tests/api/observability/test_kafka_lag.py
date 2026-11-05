"""
    Tests for how consumer lag is read and reported, against a fake consumer: no real Kafka broker.
"""
import pytest
from aiokafka import TopicPartition

from api.observability import kafka_lag
from api.observability.kafka_lag import ConsumerLagSampler, read_topic_lags
from api.observability.kafka_metrics import KafkaMetrics

REVIEW_0 = TopicPartition("review.requested", 0)
REVIEW_1 = TopicPartition("review.requested", 1)
INDEX_0 = TopicPartition("repo.file.index", 0)


class FakeLagConsumer:
    def __init__(
        self,
        *,
        end_offsets: dict[TopicPartition, int],
        committed: dict[TopicPartition, int | None],
        beginning: dict[TopicPartition, int] | None = None,
    ) -> None:
        self._end_offsets = end_offsets
        self._committed = committed
        self._beginning = beginning or {}

    def assignment(self) -> set[TopicPartition]:
        return set(self._end_offsets)

    async def end_offsets(self, partitions: list[TopicPartition]) -> dict[TopicPartition, int]:
        return {partition: self._end_offsets[partition] for partition in partitions}

    async def committed(self, partition: TopicPartition) -> int | None:
        return self._committed.get(partition)

    async def beginning_offsets(self, partitions: list[TopicPartition]) -> dict[TopicPartition, int]:
        return {partition: self._beginning.get(partition, 0) for partition in partitions}


class BrokenLagConsumer:
    def assignment(self) -> set[TopicPartition]:
        raise ConnectionError("broker unreachable")


@pytest.mark.asyncio
async def test_lag_is_the_end_offset_minus_the_committed_offset() -> None:
    """Verify lag counts the messages published and not yet committed."""
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 10}, committed={REVIEW_0: 7})

    assert await read_topic_lags(consumer) == {"review.requested": 3}


@pytest.mark.asyncio
async def test_partitions_of_one_topic_are_summed() -> None:
    """Verify a consumer holding two partitions of a topic reports their combined lag."""
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 10, REVIEW_1: 5}, committed={REVIEW_0: 7, REVIEW_1: 5})

    assert await read_topic_lags(consumer) == {"review.requested": 3}


@pytest.mark.asyncio
async def test_each_topic_is_reported_on_its_own() -> None:
    """Verify topics are not mixed together."""
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 4, INDEX_0: 9}, committed={REVIEW_0: 4, INDEX_0: 1})

    assert await read_topic_lags(consumer) == {"review.requested": 0, "repo.file.index": 8}


@pytest.mark.asyncio
async def test_a_partition_with_nothing_committed_counts_from_its_first_offset() -> None:
    """Verify a new group that has committed nothing reports the whole retained backlog."""
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 10}, committed={}, beginning={REVIEW_0: 4})

    assert await read_topic_lags(consumer) == {"review.requested": 6}


@pytest.mark.asyncio
async def test_lag_is_never_negative() -> None:
    """Verify a committed offset ahead of a stale end offset does not report a negative lag."""
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 5}, committed={REVIEW_0: 8})

    assert await read_topic_lags(consumer) == {"review.requested": 0}


@pytest.mark.asyncio
async def test_a_consumer_with_no_partitions_reports_no_lag() -> None:
    """Verify a consumer that holds nothing right now (for example mid-rebalance) reports an empty result."""
    assert await read_topic_lags(FakeLagConsumer(end_offsets={}, committed={})) == {}


@pytest.mark.asyncio
async def test_the_sampler_reports_what_it_measured(
    monkeypatch: pytest.MonkeyPatch, isolated_kafka_metrics: KafkaMetrics
) -> None:
    """Verify one sample reaches the metrics hook under the consumer's name."""
    recorded: list[tuple[str, str, int]] = []
    monkeypatch.setattr(kafka_lag.kafka_metrics, "record_consumer_lag", lambda *args: recorded.append(args))
    consumer = FakeLagConsumer(end_offsets={REVIEW_0: 10}, committed={REVIEW_0: 7})

    await ConsumerLagSampler("ReviewRequestConsumer", consumer)._sample_once()

    assert recorded == [("ReviewRequestConsumer", "review.requested", 3)]


@pytest.mark.asyncio
async def test_a_failed_measurement_is_swallowed_and_reports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify observability trouble never raises into the consumer it watches."""
    recorded: list[tuple] = []
    monkeypatch.setattr(kafka_lag.kafka_metrics, "record_consumer_lag", lambda *args: recorded.append(args))

    await ConsumerLagSampler("ReviewRequestConsumer", BrokenLagConsumer())._sample_once()

    assert recorded == []


@pytest.mark.asyncio
async def test_a_sampler_can_be_started_and_stopped() -> None:
    """Verify stopping cancels the background task without raising."""
    sampler = ConsumerLagSampler("ReviewRequestConsumer", FakeLagConsumer(end_offsets={}, committed={}))

    sampler.start()
    await sampler.stop()


@pytest.mark.asyncio
async def test_stopping_a_sampler_that_never_started_does_nothing() -> None:
    """Verify stop is safe to call without start."""
    await ConsumerLagSampler("ReviewRequestConsumer", FakeLagConsumer(end_offsets={}, committed={})).stop()
