"""
    Publishes repo.registered messages so the indexing consumer can pick up
    a newly registered repo without blocking the request that registered it.
"""
import asyncio
import logging

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from aiokafka.structs import RecordMetadata

from api.schemas.indexing import RepoRegisteredMessage

logger = logging.getLogger(__name__)


class RepoRegisteredPublishError(Exception):
    """Raised when a repo.registered message cannot be published to Kafka."""


class DlqPublishError(Exception):
    """Raised when a failed message cannot be forwarded to its dead-letter topic."""


class RepoIndexProducer:
    """Publishes repo.registered messages to Kafka for the indexing consumer; one instance lives for the app's lifetime."""

    _MAX_PUBLISH_ATTEMPTS = 3
    _INITIAL_RETRY_BACKOFF_SECONDS = 0.5

    def __init__(self, bootstrap_servers: str, topic: str, producer: AIOKafkaProducer | None = None) -> None:
        self._topic = topic
        self._producer = producer or AIOKafkaProducer(bootstrap_servers=bootstrap_servers, acks="all")

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish_repo_registered(self, message: RepoRegisteredMessage) -> None:
        try:
            metadata = await self._send_with_retry(
                self._topic, message.model_dump_json().encode(), str(message.repo_id).encode()
            )
        except KafkaError as error:
            logger.error("Failed to publish repo.registered for repo_id=%s", message.repo_id, exc_info=error)
            raise RepoRegisteredPublishError(f"Could not publish repo.registered for repo_id={message.repo_id}") from error
        logger.info(
            "Published repo.registered repo_id=%s partition=%s offset=%s",
            message.repo_id,
            metadata.partition,
            metadata.offset,
        )

    async def publish_to_dlq(self, dlq_topic: str, payload: bytes, key: bytes | None, error: Exception) -> None:
        headers = [("error_type", type(error).__name__.encode()), ("error_message", str(error).encode())]
        try:
            metadata = await self._send_with_retry(dlq_topic, payload, key, headers)
        except KafkaError as dlq_error:
            logger.error("Failed to publish to DLQ topic=%s", dlq_topic, exc_info=dlq_error)
            raise DlqPublishError(f"Could not publish to DLQ topic={dlq_topic}") from dlq_error
        logger.info("Published to DLQ topic=%s partition=%s offset=%s", dlq_topic, metadata.partition, metadata.offset)

    async def _send_with_retry(
        self, topic: str, value: bytes, key: bytes | None, headers: list[tuple[str, bytes]] | None = None
    ) -> RecordMetadata:
        backoff_seconds = self._INITIAL_RETRY_BACKOFF_SECONDS
        for attempt in range(1, self._MAX_PUBLISH_ATTEMPTS + 1):
            try:
                return await self._producer.send_and_wait(topic, value=value, key=key, headers=headers)
            except KafkaError as error:
                if attempt == self._MAX_PUBLISH_ATTEMPTS:
                    raise
                logger.warning(
                    "Kafka publish attempt %d/%d to topic=%s failed, retrying in %.1fs",
                    attempt,
                    self._MAX_PUBLISH_ATTEMPTS,
                    topic,
                    backoff_seconds,
                    exc_info=error,
                )
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
        raise AssertionError("unreachable")
