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
from api.schemas.indexing import RepoRegisteredMessage

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = 'repo_index_workflow_consumer'
TOPIC = settings.kafka_repo_registered_topic
DLQ_TOPIC = settings.kafka_repo_registered_dlq_topic
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoRegisteredMessageParseError(Exception):
    """Raised when a repo.registered message cannot be parsed into a RepoRegisteredMessage."""


@dataclass(frozen=True)
class RepoIndexConsumerDependencies:
    """Collaborators RepoIndexConsumer needs beyond Kafka wiring: indexing itself, and where to send failures."""

    indexer_dependencies: RepoIndexerDependencies
    dlq_producer: RepoIndexProducer


class RepoIndexConsumer(ConsumerInterface):
    """Consumes repo.registered messages and hands each one to a RepoIndexer."""

    def __init__(self, dependencies: RepoIndexConsumerDependencies, topic: str = TOPIC,
                 bootstrap_servers: str = BOOTSTRAP_SERVER, group_id: str = GROUP_ID) -> None:
        super().__init__(topic, bootstrap_servers, group_id, enable_auto_commit=False)
        self._indexer = RepoIndexer(dependencies.indexer_dependencies)
        self._dlq_producer = dependencies.dlq_producer

    async def consume(self) -> None:
        """
            Concrete implementation of this consumer
        """
        consumer = self._build()
        await consumer.start()
        try:
            async for msg in consumer:
                await self._process_message(msg, consumer)
        finally:
            await consumer.stop()

    async def _process_message(self, msg: ConsumerRecord, consumer: AIOKafkaConsumer) -> None:
        try:
            repo_msg = self._parse_message(msg.value)
            await self._indexer.index_repo(repo_msg)
        except Exception as error:
            logger.error("Failed to process repo.registered message at offset=%s", msg.offset, exc_info=error)
            await self._dlq_producer.publish_to_dlq(DLQ_TOPIC, msg.value, msg.key, error)
        await consumer.commit()

    def _parse_message(self, payload: bytes) -> RepoRegisteredMessage:
        try:
            return RepoRegisteredMessage.model_validate_json(payload)
        except ValidationError as error:
            raise RepoRegisteredMessageParseError("Could not parse repo.registered message") from error
