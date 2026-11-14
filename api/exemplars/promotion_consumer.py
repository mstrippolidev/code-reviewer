"""
    Concrete consumer class for exemplar-promotion.requested: puts one nominated file to the judge panel and
    records the decision, keeping at most one promoted file per repo and agent.
"""
import asyncio
import hashlib
import logging
from dataclasses import dataclass

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.engine import DatabaseEngine
from api.db.models.exemplar_promotion import ExemplarPromotion, PromotionOutcome
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo
from api.exemplars.topics import EXEMPLAR_PROMOTION_REQUESTED, EXEMPLAR_PROMOTION_REQUESTED_DLQ
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.producer import RepoIndexProducer
from api.repos.repo_data import repo_data_of
from api.schemas.exemplars import ExemplarPromotionRequestedMessage
from code_reviewer.rag.exemplar_promotion import ExemplarCandidate, ExemplarPromoter
from code_reviewer.rag.exemplars import ExemplarSource

logger = logging.getLogger(__name__)

GROUP_ID = "exemplar_promotion_consumer"
MIN_PROMOTION_JUDGES = 2


class ExemplarPromotionMessageParseError(Exception):
    """Raised when an exemplar-promotion.requested message cannot be parsed."""


class NominatedFileUnavailableError(Exception):
    """Raised when the nominated repo or file is no longer registered or indexed."""


class NominationAlreadySettledError(Exception):
    """Raised when the repo already has an exemplar for the agent, or this file content was already judged."""


@dataclass(frozen=True)
class ExemplarPromotionConsumerDependencies:
    """Collaborators ExemplarPromotionConsumer needs to decide one nomination."""

    database_engine: DatabaseEngine
    promoter: ExemplarPromoter
    dlq_producer: RepoIndexProducer


class ExemplarPromotionConsumer(ConsumerInterface[ExemplarPromotionRequestedMessage]):
    """Consumes exemplar-promotion.requested, one nominated file at a time."""

    def __init__(self, dependencies: ExemplarPromotionConsumerDependencies, bootstrap_servers: str) -> None:
        super().__init__(EXEMPLAR_PROMOTION_REQUESTED, bootstrap_servers, GROUP_ID, enable_auto_commit=False)
        self._dependencies = dependencies

    def _parse_msg(self, msg: ConsumerRecord) -> ExemplarPromotionRequestedMessage:
        try:
            return ExemplarPromotionRequestedMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise ExemplarPromotionMessageParseError("Could not parse exemplar-promotion.requested message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse exemplar-promotion.requested at offset=%s", msg.offset, exc_info=error)
        await self._send_to_dlq(msg, error)

    async def _handle_parsed_message(
        self, message: ExemplarPromotionRequestedMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            await self._decide(message)
        except (NominatedFileUnavailableError, NominationAlreadySettledError) as error:
            logger.info("Skipping nomination of %s for %s: %s", message.file_path, message.code_key.value, error)
        except Exception as error:
            logger.exception("Exemplar promotion failed for %s (%s)", message.file_path, message.code_key.value)
            await self._send_to_dlq(msg, error)

    async def _send_to_dlq(self, msg: ConsumerRecord, error: Exception) -> None:
        await self._dependencies.dlq_producer.publish_to_dlq(EXEMPLAR_PROMOTION_REQUESTED_DLQ, msg.value, msg.key, error)

    async def _decide(self, message: ExemplarPromotionRequestedMessage) -> None:
        """Reads, then judges with no database session open, then records: the panel takes about half a minute."""
        candidate, digest = await self._prepare(message)
        outcome = await asyncio.to_thread(self._dependencies.promoter.promote, candidate)
        await self._record(message, digest, outcome.value)

    async def _prepare(self, message: ExemplarPromotionRequestedMessage) -> tuple[ExemplarCandidate, str]:
        """The file as a candidate plus its content hash.

        Raises:
            NominatedFileUnavailableError: If the repo or file is gone.
            NominationAlreadySettledError: If the repo already has an exemplar for this agent, or this content
                was judged before.
        """
        async with self._dependencies.database_engine.new_session() as session:
            repo, indexed_file = await self._load_nominated_file(message, session)
            digest = hashlib.sha256(indexed_file.content.encode()).hexdigest()
            if await self._has_promoted_exemplar(message, session):
                raise NominationAlreadySettledError("this repo already has an exemplar for the agent")
            if await self._was_judged(message, digest, session):
                raise NominationAlreadySettledError("this file content was already judged")
        candidate = ExemplarCandidate(
            repo_data=repo_data_of(repo),
            code_key=message.code_key,
            source=ExemplarSource(message.file_path, indexed_file.content),
        )
        return candidate, digest

    async def _record(self, message: ExemplarPromotionRequestedMessage, digest: str, outcome_value: str) -> None:
        async with self._dependencies.database_engine.new_session() as session:
            session.add(
                ExemplarPromotion(
                    repo_id=message.repo_id,
                    file_path=message.file_path,
                    code_key=message.code_key.value,
                    content_digest=digest,
                    outcome=PromotionOutcome(outcome_value),
                )
            )
            await session.commit()

    async def _load_nominated_file(
        self, message: ExemplarPromotionRequestedMessage, session: AsyncSession
    ) -> tuple[RegisteredRepo, IndexedFile]:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == message.repo_id))
        indexed_file = await session.scalar(
            select(IndexedFile).where(
                IndexedFile.repo_id == message.repo_id,
                IndexedFile.file_path == message.file_path,
                IndexedFile.status == IndexedFileStatus.INDEXED,
            )
        )
        if repo is None or indexed_file is None:
            raise NominatedFileUnavailableError(f"repo_id={message.repo_id} no longer has this file indexed")
        return repo, indexed_file

    async def _has_promoted_exemplar(self, message: ExemplarPromotionRequestedMessage, session: AsyncSession) -> bool:
        promoted = await session.scalar(
            select(ExemplarPromotion.id).where(
                ExemplarPromotion.repo_id == message.repo_id,
                ExemplarPromotion.code_key == message.code_key.value,
                ExemplarPromotion.outcome == PromotionOutcome.PROMOTED,
            )
        )
        return promoted is not None

    async def _was_judged(
        self, message: ExemplarPromotionRequestedMessage, digest: str, session: AsyncSession
    ) -> bool:
        decided = await session.scalar(
            select(ExemplarPromotion.id).where(
                ExemplarPromotion.repo_id == message.repo_id,
                ExemplarPromotion.file_path == message.file_path,
                ExemplarPromotion.code_key == message.code_key.value,
                ExemplarPromotion.content_digest == digest,
            )
        )
        return decided is not None
