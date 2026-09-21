"""
    Concrete consumer class to process each file separate
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.producer import RepoIndexProducer
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from api.indexing.topics import REPO_FILE_INDEX, REPO_FILE_INDEX_DLQ, REPO_FILE_PROGRESS
from api.schemas.indexing import RepoFileIndexMessage
from api.schemas.repos import RepoFileProgressMessage
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData

logger = logging.getLogger(__name__)

settings = get_api_settings()

GROUP_ID = "repo_file_index_consumer"
TOPIC = REPO_FILE_INDEX
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class RepoFileIndexMessageParseError(Exception):
    """Raised when a repo.file.index message cannot be parsed into a RepoFileIndexMessage."""


@dataclass(frozen=True)
class RepoFileIndexConsumerDependencies:
    """Collaborators RepoFileIndexConsumer needs to embed one file and record the outcome."""

    database_engine: DatabaseEngine
    rag_manager: LlamaIndexRagManager
    repo_producer: RepoIndexProducer
    completion_finalizer: RepoCompletionFinalizer
    max_concurrent_file_indexing: int


class RepoFileIndexConsumer(ConsumerInterface[RepoFileIndexMessage]):
    """Consumes repo.file.index; many instances share one group so Kafka partitions the work across them."""

    def __init__(self, dependencies: RepoFileIndexConsumerDependencies) -> None:
        super().__init__(TOPIC, BOOTSTRAP_SERVER, GROUP_ID, enable_auto_commit=False)
        self.dependencies = dependencies
        self._semaphore = asyncio.Semaphore(self.dependencies.max_concurrent_file_indexing)

    def _parse_msg(self, msg: ConsumerRecord) -> RepoFileIndexMessage:
        try:
            return RepoFileIndexMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise RepoFileIndexMessageParseError("Could not parse repo.file.index message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse repo.file.index message at offset=%s", msg.offset, exc_info=error)
        await self.dependencies.repo_producer.publish_to_dlq(REPO_FILE_INDEX_DLQ, msg.value, msg.key, error)

    async def _handle_parsed_message(
        self, file_msg: RepoFileIndexMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self._index_file(file_msg)
        except Exception as error:
            logger.exception(
                "Unexpected failure processing repo.file.index for repo_id=%s file_path=%s",
                file_msg.repo_id, file_msg.file_path,
            )
            await self._mark_failed_best_effort(file_msg, error)

    async def _mark_failed_best_effort(self, file_msg: RepoFileIndexMessage, error: Exception) -> None:
        try:
            async with self.dependencies.database_engine.new_session() as session:
                indexed_file = await session.scalar(
                    select(IndexedFile).where(
                        IndexedFile.repo_id == file_msg.repo_id, IndexedFile.file_path == file_msg.file_path
                    )
                )
                if indexed_file is None:
                    return
                indexed_file.status = IndexedFileStatus.FAILED
                indexed_file.status_reason = str(error)
                await session.commit()
                await self.dependencies.completion_finalizer.finalize_if_complete(file_msg.repo_id, session)
        except Exception:
            logger.exception(
                "Could not mark repo_id=%s file_path=%s FAILED after an earlier failure",
                file_msg.repo_id, file_msg.file_path,
            )

    async def _index_file(self, file_msg: RepoFileIndexMessage) -> None:
        async with self.dependencies.database_engine.new_session() as session:
            indexed_file = await session.scalar(
                select(IndexedFile).where(
                    IndexedFile.repo_id == file_msg.repo_id, IndexedFile.file_path == file_msg.file_path
                )
            )
            if indexed_file is None:
                logger.warning(
                    "No IndexedFile row for repo_id=%s file_path=%s — dropping message",
                    file_msg.repo_id, file_msg.file_path,
                )
                return
            indexed_file.status = IndexedFileStatus.PROCESSING
            await session.commit()
            await self._embed_and_record(file_msg, indexed_file, session)
            await self.dependencies.completion_finalizer.finalize_if_complete(file_msg.repo_id, session)

    async def _embed_and_record(
        self, file_msg: RepoFileIndexMessage, indexed_file: IndexedFile, session: AsyncSession
    ) -> None:
        repo_data = RepoData(
            repo_id=str(file_msg.repo_id), commit_sha=file_msg.commit_sha, owner_id=str(file_msg.owner_id)
        )
        try:
            async with self._semaphore:
                logger.info("Embedding started file_path=%s repo_id=%s", file_msg.file_path, file_msg.repo_id)
                await asyncio.to_thread(
                    self.dependencies.rag_manager.index_file, repo_data, file_msg.file_path, file_msg.content
                )
        except Exception as error:
            logger.error("Failed to index %s for repo_id=%s", file_msg.file_path, file_msg.repo_id, exc_info=error)
            indexed_file.status = IndexedFileStatus.FAILED
            indexed_file.status_reason = str(error)
        else:
            indexed_file.status = IndexedFileStatus.INDEXED
            indexed_file.indexed_at = datetime.now(UTC).replace(tzinfo=None)
        logger.info(
            "Embedding finished file_path=%s repo_id=%s status=%s",
            file_msg.file_path, file_msg.repo_id, indexed_file.status,
        )
        await session.commit()
        try:
            await self.dependencies.repo_producer.publish(
                REPO_FILE_PROGRESS,
                RepoFileProgressMessage(
                    repo_id=file_msg.repo_id, file_path=file_msg.file_path,
                    status=indexed_file.status, status_reason=indexed_file.status_reason,
                ),
                f"{file_msg.repo_id}:{file_msg.file_path}".encode(),
            )
        except Exception:
            # A lost notification, not a lost result — indexed_file.status is already committed.
            logger.exception(
                "Failed to publish repo.file.progress for repo_id=%s file_path=%s",
                file_msg.repo_id, file_msg.file_path,
            )
