"""
    Concrete class for the repo_index consumers.
"""
import logging
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError

from api.config.settings import get_api_settings
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.producer import RepoIndexProducer
from api.indexing.repo_indexer import RepoIndexer, RepoIndexerDependencies
from api.indexing.topics import REPO_REGISTERED, REPO_REGISTERED_DLQ
from api.schemas.indexing import RepoRegisteredMessage

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = 'repo_index_workflow_consumer'
TOPIC = REPO_REGISTERED
DLQ_TOPIC = REPO_REGISTERED_DLQ
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoRegisteredMessageParseError(Exception):
    """Raised when a repo.registered message cannot be parsed into a RepoRegisteredMessage."""


@dataclass(frozen=True)
class RepoIndexConsumerDependencies:
    """Collaborators RepoIndexConsumer needs beyond Kafka wiring: indexing itself, and where to send failures."""

    indexer_dependencies: RepoIndexerDependencies
    dlq_producer: RepoIndexProducer


class RepoIndexConsumer(ConsumerInterface[RepoRegisteredMessage]):
    """Consumes repo.registered messages and hands each one to a RepoIndexer."""

    def __init__(self, dependencies: RepoIndexConsumerDependencies, topic: str = TOPIC,
                 bootstrap_servers: str = BOOTSTRAP_SERVER, group_id: str = GROUP_ID) -> None:
        super().__init__(topic, bootstrap_servers, group_id, enable_auto_commit=False)
        self._indexer = RepoIndexer(dependencies.indexer_dependencies)
        self._dlq_producer = dependencies.dlq_producer

    def _parse_msg(self, msg: ConsumerRecord) -> RepoRegisteredMessage:
        try:
            return RepoRegisteredMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise RepoRegisteredMessageParseError("Could not parse repo.registered message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Failed to process repo.registered message at offset=%s", msg.offset, exc_info=error)
        await self._dlq_producer.publish_to_dlq(DLQ_TOPIC, msg.value, msg.key, error)

    async def _handle_parsed_message(
        self, repo_msg: RepoRegisteredMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self._indexer.index_repo(repo_msg)
        except Exception as error:
            logger.error("Failed to process repo.registered message at offset=%s", msg.offset, exc_info=error)
            await self._dlq_producer.publish_to_dlq(DLQ_TOPIC, msg.value, msg.key, error)
