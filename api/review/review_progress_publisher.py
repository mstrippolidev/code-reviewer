"""
    Publishes review progress to Kafka so every api replica can relay it to its own SSE connections.
"""
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Protocol

from pydantic import BaseModel

from api.indexing.producer import PublishError
from api.review.review_progress_broadcaster import ReviewProgressEvent
from api.review.topics import REVIEW_PROGRESS
from api.schemas.reviews import (
    ReviewAgentProgressEnvelope,
    ReviewAgentProgressMessage,
    ReviewFileProgressEnvelope,
    ReviewFileProgressMessage,
    ReviewStatusEnvelope,
)

logger = logging.getLogger(__name__)


class ReviewProgressPublisher(ABC):
    """Where the review consumer reports progress; it never knows who is listening."""

    @abstractmethod
    async def publish(self, review_id: uuid.UUID, event: ReviewProgressEvent) -> None:
        """Delivers one progress event, never raising for a delivery failure."""


class KafkaMessageProducer(Protocol):
    """The slice of RepoIndexProducer this publisher depends on."""

    async def publish(self, topic: str, message: BaseModel, key: bytes) -> None: ...


class KafkaReviewProgressPublisher(ReviewProgressPublisher):
    """Sends every event to review.progress, keyed by review_id so one review's events stay in order."""

    def __init__(self, producer: KafkaMessageProducer) -> None:
        self._producer = producer

    async def publish(self, review_id: uuid.UUID, event: ReviewProgressEvent) -> None:
        try:
            await self._producer.publish(REVIEW_PROGRESS, _wrap_in_envelope(event), str(review_id).encode())
        except PublishError:
            logger.exception("Could not publish review progress for review_id=%s", review_id)


def _wrap_in_envelope(event: ReviewProgressEvent) -> BaseModel:
    if isinstance(event, ReviewAgentProgressMessage):
        return ReviewAgentProgressEnvelope(event=event)
    if isinstance(event, ReviewFileProgressMessage):
        return ReviewFileProgressEnvelope(event=event)
    return ReviewStatusEnvelope(event=event)
