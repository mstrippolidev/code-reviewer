"""
    Relays repo.file.progress/repo.status.progress into this process's RepoProgressBroadcaster.
"""
import logging
import uuid
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError

from api.config.settings import get_api_settings
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.repo_progress_broadcaster import ProgressEvent, RepoProgressBroadcaster
from api.indexing.topics import REPO_FILE_PROGRESS, REPO_STATUS_PROGRESS
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID_PREFIX = "repo_progress_consumer"
TOPICS = (REPO_FILE_PROGRESS, REPO_STATUS_PROGRESS)
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoProgressMessageParseError(Exception):
    """Raised when a repo.file.progress/repo.status.progress message cannot be parsed."""


@dataclass(frozen=True)
class RepoProgressConsumerDependencies:
    """Collaborators RepoProgressConsumer needs to relay a Kafka progress event into the broadcaster."""

    broadcaster: RepoProgressBroadcaster


class RepoProgressConsumer(ConsumerInterface[ProgressEvent]):
    """Mirrors every repo.file.progress/repo.status.progress event into a local RepoProgressBroadcaster.

    Each instance uses its own unique consumer group (never shared) so every replica independently
    receives every event, unlike RepoFileIndexConsumer which shares one group to split up the work.
    """

    def __init__(self, dependencies: RepoProgressConsumerDependencies, group_id: str | None = None) -> None:
        resolved_group_id = group_id or f"{GROUP_ID_PREFIX}-{uuid.uuid4().hex}"
        super().__init__(TOPICS, BOOTSTRAP_SERVER, resolved_group_id, enable_auto_commit=False)
        self.dependencies = dependencies

    def _parse_msg(self, msg: ConsumerRecord) -> ProgressEvent:
        try:
            if msg.topic == REPO_FILE_PROGRESS:
                return RepoFileProgressMessage.model_validate_json(msg.value)
            if msg.topic == REPO_STATUS_PROGRESS:
                return RepoStatusProgressMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise RepoProgressMessageParseError(f"Could not parse message on topic={msg.topic}") from error
        raise RepoProgressMessageParseError(f"Unexpected topic={msg.topic}")

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse message on topic=%s offset=%s", msg.topic, msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, event: ProgressEvent, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self.dependencies.broadcaster.publish(event.repo_id, event)
        except Exception:
            logger.exception("Failed to broadcast repo_id=%s event from topic=%s", event.repo_id, msg.topic)
