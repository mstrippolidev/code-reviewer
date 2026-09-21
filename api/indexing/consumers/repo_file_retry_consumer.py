"""
    Concrete consumer class for repo.file.retry: re-dispatches only a repo's FAILED files.
"""
import logging
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError

from api.config.settings import get_api_settings
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.repo_indexer import RepoIndexer, RepoIndexerDependencies
from api.indexing.topics import REPO_FILE_RETRY
from api.schemas.indexing import RepoRegisteredMessage

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = "repo_file_retry_consumer"
TOPIC = REPO_FILE_RETRY
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoFileRetryMessageParseError(Exception):
    """Raised when a repo.file.retry message cannot be parsed into a RepoRegisteredMessage."""


@dataclass(frozen=True)
class RepoFileRetryConsumerDependencies:
    """Collaborators RepoFileRetryConsumer needs to re-fetch a repo and re-dispatch its FAILED files."""

    indexer_dependencies: RepoIndexerDependencies


class RepoFileRetryConsumer(ConsumerInterface[RepoRegisteredMessage]):
    """Consumes repo.file.retry and hands each one to a RepoIndexer's retry_failed_files."""

    def __init__(self, dependencies: RepoFileRetryConsumerDependencies, topic: str = TOPIC,
                 bootstrap_servers: str = BOOTSTRAP_SERVER, group_id: str = GROUP_ID) -> None:
        super().__init__(topic, bootstrap_servers, group_id, enable_auto_commit=False)
        self._indexer = RepoIndexer(dependencies.indexer_dependencies)

    def _parse_msg(self, msg: ConsumerRecord) -> RepoRegisteredMessage:
        try:
            return RepoRegisteredMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise RepoFileRetryMessageParseError("Could not parse repo.file.retry message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse repo.file.retry message at offset=%s", msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, repo_msg: RepoRegisteredMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self._indexer.retry_failed_files(repo_msg)
        except Exception:
            logger.exception("Failed to process repo.file.retry message at offset=%s", msg.offset)
