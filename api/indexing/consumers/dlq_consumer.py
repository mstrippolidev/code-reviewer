"""
    Consumes every dead-letter topic: notifies a human per message, no retry, no reprocessing.
"""
import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, ConsumerRecord

from api.config.settings import get_api_settings
from api.indexing.consumers.dlq_notifier import DlqNotifier
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.topics import REPO_FILE_INDEX_DLQ, REPO_REGISTERED_DLQ
from api.review.topics import REVIEW_REQUESTED_DLQ

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = "dlq_notification_consumer"
TOPICS = (REPO_REGISTERED_DLQ, REPO_FILE_INDEX_DLQ, REVIEW_REQUESTED_DLQ)
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


@dataclass(frozen=True)
class DeadLetter:
    """The facts about one dead-lettered message, without its payload, which may hold private repo content."""

    topic: str
    partition: int
    offset: int
    key: str
    error_type: str
    error_message: str


class DlqConsumer(ConsumerInterface[DeadLetter]):
    """Sends one notification per message that lands on any dead-letter topic."""

    def __init__(self, notifier: DlqNotifier) -> None:
        super().__init__(TOPICS, BOOTSTRAP_SERVER, GROUP_ID, enable_auto_commit=False)
        self._notifier = notifier

    def _parse_msg(self, msg: ConsumerRecord) -> DeadLetter:
        error_type, error_message = _read_error_headers(msg.headers)
        return DeadLetter(
            topic=msg.topic,
            partition=msg.partition,
            offset=msg.offset,
            key=_decode(msg.key) or "none",
            error_type=error_type,
            error_message=error_message,
        )

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not interpret DLQ message at offset=%s", msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, parsed: DeadLetter, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await asyncio.to_thread(
                self._notifier.notify, f"{parsed.topic}: {parsed.error_type}", _build_notification_body(parsed)
            )
        except Exception as error:
            logger.error("Failed to send DLQ notification for topic=%s offset=%s", parsed.topic, parsed.offset,
                         exc_info=error)


def _build_notification_body(dead_letter: DeadLetter) -> str:
    return (
        f"topic: {dead_letter.topic}\n"
        f"partition: {dead_letter.partition}\n"
        f"offset: {dead_letter.offset}\n"
        f"key: {dead_letter.key}\n"
        f"error_type: {dead_letter.error_type}\n"
        f"error_message: {dead_letter.error_message}"
    )


def _read_error_headers(headers: Sequence[tuple[str, bytes]]) -> tuple[str, str]:
    header_values = dict(headers)
    error_type = _decode(header_values.get("error_type")) or "UnknownError"
    error_message = _decode(header_values.get("error_message"))
    return error_type, error_message


def _decode(raw: bytes | None) -> str:
    return raw.decode(errors="replace") if raw else ""
