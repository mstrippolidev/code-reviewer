"""
    Periodically measures how far each consumer is behind the end of its topics.
"""
import asyncio
import logging
from contextlib import suppress

from aiokafka import AIOKafkaConsumer, TopicPartition

from api.observability.kafka_metrics import kafka_metrics

logger = logging.getLogger(__name__)

_SAMPLE_INTERVAL_SECONDS = 15


class ConsumerLagSampler:
    """Reads one consumer's lag on a timer and reports it; a failed read is logged and never stops the consumer."""

    def __init__(self, consumer_name: str, consumer: AIOKafkaConsumer) -> None:
        self._consumer_name = consumer_name
        self._consumer = consumer
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Starts sampling in the background."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stops sampling and waits for the background task to end."""
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(_SAMPLE_INTERVAL_SECONDS)
            await self._sample_once()

    async def _sample_once(self) -> None:
        try:
            lags = await read_topic_lags(self._consumer)
        except Exception:
            logger.warning("Could not read the lag of consumer=%s", self._consumer_name, exc_info=True)
            return
        for topic, lag in lags.items():
            kafka_metrics.record_consumer_lag(self._consumer_name, topic, lag)


async def read_topic_lags(consumer: AIOKafkaConsumer) -> dict[str, int]:
    """Messages not yet committed, per topic, summed over the partitions this consumer holds."""
    partitions = list(consumer.assignment())
    if not partitions:
        return {}
    end_offsets = await consumer.end_offsets(partitions)
    lags: dict[str, int] = {}
    for partition in partitions:
        committed = await _committed_or_start(consumer, partition)
        lags[partition.topic] = lags.get(partition.topic, 0) + max(0, end_offsets[partition] - committed)
    return lags


async def _committed_or_start(consumer: AIOKafkaConsumer, partition: TopicPartition) -> int:
    """The group's committed offset, or the partition's first offset when it has committed nothing yet."""
    committed = await consumer.committed(partition)
    if committed is not None:
        return committed
    return (await consumer.beginning_offsets([partition]))[partition]
