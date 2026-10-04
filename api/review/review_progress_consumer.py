"""
    Relays review.progress into this process's ReviewProgressBroadcaster.
"""
import logging
import uuid

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import TypeAdapter, ValidationError

from api.config.settings import get_api_settings
from api.indexing.consumers.interface import ConsumerInterface
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster, ReviewProgressEvent
from api.review.topics import REVIEW_PROGRESS
from api.schemas.reviews import ReviewProgressEnvelope

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID_PREFIX = "review_progress_consumer"
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers

_ENVELOPE_ADAPTER: TypeAdapter[ReviewProgressEnvelope] = TypeAdapter(ReviewProgressEnvelope)


class ReviewProgressMessageParseError(Exception):
    """Raised when a review.progress message cannot be parsed."""


class ReviewProgressConsumer(ConsumerInterface[ReviewProgressEvent]):
    """Mirrors every review.progress event into the local ReviewProgressBroadcaster.

    Each instance joins its own unique consumer group so every replica receives every event and can
    feed the SSE connections that happen to be attached to it, regardless of which replica ran the review.
    """

    def __init__(self, broadcaster: ReviewProgressBroadcaster) -> None:
        group_id = f"{GROUP_ID_PREFIX}-{uuid.uuid4().hex}"
        super().__init__(
            REVIEW_PROGRESS, BOOTSTRAP_SERVER, group_id, enable_auto_commit=False, auto_offset_reset="latest"
        )
        self._broadcaster = broadcaster

    def _parse_msg(self, msg: ConsumerRecord) -> ReviewProgressEvent:
        try:
            return _ENVELOPE_ADAPTER.validate_json(msg.value).event
        except ValidationError as error:
            raise ReviewProgressMessageParseError(f"Could not parse message at offset={msg.offset}") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse review.progress message offset=%s", msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, event: ReviewProgressEvent, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self._broadcaster.publish(event.review_id, event)
        except Exception:
            logger.exception("Failed to broadcast review_id=%s event", event.review_id)
