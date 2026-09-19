"""
    Publishes indexing-pipeline messages to Kafka; one instance lives for the app's lifetime.
"""
import logging

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_MS = 10_000


class PublishError(Exception):
    """Raised when a message cannot be published to Kafka."""


class DlqPublishError(Exception):
    """Raised when a failed message cannot be forwarded to its dead-letter topic."""


class RepoIndexProducer:
    """Publishes indexing-pipeline messages to Kafka; one instance lives for the app's lifetime."""

    def __init__(self, bootstrap_servers: str, producer: AIOKafkaProducer | None = None) -> None:
        self._producer = producer or AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers, acks="all", request_timeout_ms=_REQUEST_TIMEOUT_MS
        )

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None:
        try:
            metadata = await self._producer.send_and_wait(topic, value=message.model_dump_json().encode(), key=key)
        except KafkaError as error:
            raise PublishError(f"Could not publish {type(message).__name__} to topic={topic}") from error
        logger.info(
            "Published %s to topic=%s partition=%s offset=%s",
            type(message).__name__,
            topic,
            metadata.partition,
            metadata.offset,
        )

    async def publish_to_dlq(self, dlq_topic: str, payload: bytes, key: bytes | None, error: Exception) -> None:
        headers = [("error_type", type(error).__name__.encode()), ("error_message", str(error).encode())]
        try:
            metadata = await self._producer.send_and_wait(dlq_topic, value=payload, key=key, headers=headers)
        except KafkaError as dlq_error:
            logger.error("Failed to publish to DLQ topic=%s", dlq_topic, exc_info=dlq_error)
            raise DlqPublishError(f"Could not publish to DLQ topic={dlq_topic}") from dlq_error
        logger.info("Published to DLQ topic=%s partition=%s offset=%s", dlq_topic, metadata.partition, metadata.offset)
