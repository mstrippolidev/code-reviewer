"""
    Concrete consumer class for review.requested: runs the Sustainable Code pipeline
    against a set of already-indexed files and reports the finished report back.
"""
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.guest_review_file import GuestReviewFile
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.indexing.consumers.interface import ConsumerInterface
from api.indexing.producer import RepoIndexProducer
from api.review.review_progress_publisher import ReviewProgressPublisher
from api.review.topics import REVIEW_REQUESTED, REVIEW_REQUESTED_DLQ
from api.schemas.reviews import (
    ReviewAgentProgressMessage,
    ReviewFileProgressMessage,
    ReviewRequestedMessage,
    ReviewStatusMessage,
)
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline.orchestrator import (
    AGENT_EXECUTION_FAILED_REASON,
    GUARD_EXECUTION_FAILED_REASON,
    run_pipeline,
)
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import AgentReviewEntry, AggregatorOutput, CodeKey
from code_reviewer.schemas.submission import SubmittedFile

logger = logging.getLogger(__name__)

_GENERIC_FAILURE_REASON = "Review failed unexpectedly. Please try again."

settings = get_api_settings()

GROUP_ID = "review_request_consumer"
TOPIC = REVIEW_REQUESTED
BOOTSTRAP_SERVER = settings.kafka_bootstrap_servers


class ReviewRequestMessageParseError(Exception):
    """Raised when a review.requested message cannot be parsed into a ReviewRequestedMessage."""


class ReviewFilesUnavailableError(Exception):
    """Raised when a requested file is no longer an indexed row for this repo."""


class PipelineDegradedError(Exception):
    """Synthetic error for review.requested.dlq only — never raised, just
    carried as the DLQ record's error headers. The pipeline reached
    ReviewJobStatus.COMPLETED (isolation at the agent/file level worked as
    designed), but at least one agent or file failed inside it, so the
    job's own status alone doesn't say a human should check the trace."""


@dataclass(frozen=True)
class ReviewRequestConsumerDependencies:
    """Collaborators ReviewRequestConsumer needs to run one review job end to end."""

    database_engine: DatabaseEngine
    agents_container: AgentsContainer
    progress_publisher: ReviewProgressPublisher
    dlq_producer: RepoIndexProducer


class ReviewRequestConsumer(ConsumerInterface[ReviewRequestedMessage]):
    """Consumes review.requested and runs the full pipeline for one submitted file set."""

    def __init__(self, dependencies: ReviewRequestConsumerDependencies, topic: str = TOPIC,
                 bootstrap_servers: str = BOOTSTRAP_SERVER, group_id: str = GROUP_ID) -> None:
        super().__init__(topic, bootstrap_servers, group_id, enable_auto_commit=False)
        self._dependencies = dependencies

    def _parse_msg(self, msg: ConsumerRecord) -> ReviewRequestedMessage:
        try:
            return ReviewRequestedMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise ReviewRequestMessageParseError("Could not parse review.requested message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        logger.error("Could not parse review.requested message at offset=%s", msg.offset, exc_info=error)
        await self._send_to_dlq(msg, error, f"offset={msg.offset}")

    async def _handle_parsed_message(
        self, review_msg: ReviewRequestedMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        try:
            result = await self._run_review(review_msg)
        except Exception as error:
            logger.exception("Failed to process review.requested for review_id=%s", review_msg.review_id)
            await self._mark_failed_best_effort(review_msg)
            await self._send_to_dlq(msg, error, f"review_id={review_msg.review_id}")
            return
        if _has_pipeline_failures(result):
            degraded_error = PipelineDegradedError(_degraded_reason(result))
            await self._send_to_dlq(msg, degraded_error, f"review_id={review_msg.review_id}")

    async def _send_to_dlq(self, msg: ConsumerRecord, error: Exception, context: str) -> None:
        """Forwards the raw review.requested message to its dead-letter
        topic and logs an uppercase line at the exact point of the send —
        the only alerting signal until a real one is wired up, so it must
        stand out from ordinary log volume rather than blend into it."""
        logger.error(
            "REVIEW REQUEST SENT TO DLQ: %s ERROR_TYPE=%s ERROR_MESSAGE=%s",
            context.upper(), type(error).__name__.upper(), str(error).upper(),
        )
        await self._dependencies.dlq_producer.publish_to_dlq(REVIEW_REQUESTED_DLQ, msg.value, msg.key, error)

    async def _run_review(self, review_msg: ReviewRequestedMessage) -> AggregatorOutput:
        async with self._dependencies.database_engine.new_session() as session:
            job = await self._start_job(review_msg, session)
            result = await self._execute_pipeline(review_msg, job, session)
            await self._finish_job(job, result, session, review_msg)
            return result

    async def _start_job(self, review_msg: ReviewRequestedMessage, session: AsyncSession) -> ReviewJob:
        job = await self._load_job(review_msg.review_id, session)
        job.status = ReviewJobStatus.RUNNING
        await session.commit()
        await self._broadcast_status(review_msg, job)
        return job

    async def _execute_pipeline(
        self, review_msg: ReviewRequestedMessage, job: ReviewJob, session: AsyncSession
    ) -> AggregatorOutput:
        submitted_files, repo_data = await self._load_submission(review_msg, job, session)
        return await run_pipeline(
            submitted_files,
            self._dependencies.agents_container,
            repo_data,
            on_file_reviewed=self._build_progress_callback(review_msg, job, session),
            on_agent_reviewed=self._build_agent_progress_callback(review_msg),
        )

    async def _load_submission(
        self, review_msg: ReviewRequestedMessage, job: ReviewJob, session: AsyncSession
    ) -> tuple[list[SubmittedFile], RepoData | None]:
        if review_msg.is_guest_review:
            guest_files = await self._load_guest_files(job, session)
            return [SubmittedFile(file_path=f.file_path, content=f.content) for f in guest_files], None
        repo = await self._load_repo(review_msg.repo_id, session)
        files = await self._load_indexed_files(review_msg.repo_id, review_msg.file_paths, session)
        submitted_files = [SubmittedFile(file_path=f.file_path, content=f.content) for f in files]
        repo_data = RepoData(repo_id=str(repo.repo_id), owner_id=str(repo.owner_id), commit_sha=repo.commit_sha)
        return submitted_files, repo_data

    def _build_progress_callback(
        self, review_msg: ReviewRequestedMessage, job: ReviewJob, session: AsyncSession
    ) -> Callable[[str, bool, list[AgentReviewEntry]], Awaitable[None]]:
        async def on_file_reviewed(file_path: str, failed: bool, entries: list[AgentReviewEntry]) -> None:
            if entries:
                await self._persist_agent_entries(job, file_path, entries, session)
            event = ReviewFileProgressMessage(review_id=review_msg.review_id, file_path=file_path, failed=failed)
            await self._dependencies.progress_publisher.publish(review_msg.review_id, event)

        return on_file_reviewed

    async def _persist_agent_entries(
        self, job: ReviewJob, file_path: str, entries: list[AgentReviewEntry], session: AsyncSession
    ) -> None:
        agent_entries = dict(job.agent_entries or {})
        agent_entries[file_path] = {entry.code_key.value: entry.model_dump(mode="json") for entry in entries}
        job.agent_entries = agent_entries
        await session.commit()

    def _build_agent_progress_callback(
        self, review_msg: ReviewRequestedMessage
    ) -> Callable[[CodeKey, AgentReviewEntry], Awaitable[None]]:
        async def on_agent_reviewed(code_key: CodeKey, entry: AgentReviewEntry) -> None:
            event = ReviewAgentProgressMessage(
                review_id=review_msg.review_id, file_path=entry.file_path, code_key=code_key, entry=entry
            )
            await self._dependencies.progress_publisher.publish(review_msg.review_id, event)

        return on_agent_reviewed

    async def _finish_job(
        self, job: ReviewJob, result: AggregatorOutput, session: AsyncSession, review_msg: ReviewRequestedMessage
    ) -> None:
        job.result = result.model_dump(mode="json")
        job.status = ReviewJobStatus.COMPLETED
        job.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        await self._broadcast_status(review_msg, job)

    async def _load_job(self, review_id, session: AsyncSession) -> ReviewJob:
        job = await session.scalar(select(ReviewJob).where(ReviewJob.review_id == review_id))
        if job is None:
            raise ReviewFilesUnavailableError(f"No ReviewJob row for review_id={review_id}")
        return job

    async def _load_repo(self, repo_id: int, session: AsyncSession) -> RegisteredRepo:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None:
            raise ReviewFilesUnavailableError(f"No RegisteredRepo row for repo_id={repo_id}")
        return repo

    async def _load_indexed_files(
        self, repo_id: int, file_paths: list[str], session: AsyncSession
    ) -> list[IndexedFile]:
        result = await session.scalars(
            select(IndexedFile).where(
                IndexedFile.repo_id == repo_id,
                IndexedFile.file_path.in_(file_paths),
                IndexedFile.status == IndexedFileStatus.INDEXED,
            )
        )
        files = list(result.all())
        if len(files) != len(file_paths):
            raise ReviewFilesUnavailableError(
                f"Only {len(files)} of {len(file_paths)} requested files are still indexed for repo_id={repo_id}"
            )
        return files

    async def _load_guest_files(self, job: ReviewJob, session: AsyncSession) -> list[GuestReviewFile]:
        result = await session.scalars(
            select(GuestReviewFile).where(GuestReviewFile.review_job_id == job.id).order_by(GuestReviewFile.id)
        )
        files = list(result.all())
        if not files:
            raise ReviewFilesUnavailableError(f"No guest files stored for review_id={job.review_id}")
        return files

    async def _broadcast_status(self, review_msg: ReviewRequestedMessage, job: ReviewJob) -> None:
        result = AggregatorOutput.model_validate(job.result) if job.result else None
        event = ReviewStatusMessage(
            review_id=review_msg.review_id,
            repo_id=review_msg.repo_id,
            status=job.status,
            status_reason=job.status_reason,
            file_paths=review_msg.file_paths,
            result=result,
            agent_entries=job.agent_entries,
        )
        await self._dependencies.progress_publisher.publish(review_msg.review_id, event)

    async def _mark_failed_best_effort(self, review_msg: ReviewRequestedMessage) -> None:
        try:
            async with self._dependencies.database_engine.new_session() as session:
                job = await session.scalar(select(ReviewJob).where(ReviewJob.review_id == review_msg.review_id))
                if job is None:
                    return
                job.status = ReviewJobStatus.FAILED
                job.status_reason = _GENERIC_FAILURE_REASON
                await session.commit()
                await self._broadcast_status(review_msg, job)
        except Exception:
            logger.exception("Could not mark review_id=%s FAILED after an earlier failure", review_msg.review_id)


_UNEXPECTED_SKIP_REASONS = frozenset({AGENT_EXECUTION_FAILED_REASON, GUARD_EXECUTION_FAILED_REASON})


def _has_pipeline_failures(result: AggregatorOutput) -> bool:
    """True when the pipeline finished (job status COMPLETED) but at least
    one agent or file failed inside it — the isolation that keeps a job
    completing despite that failure also means job status alone can't
    tell anyone to go check the trace."""
    if any(entry.agents_failed for entry in result.review):
        return True
    return any(skipped.reason in _UNEXPECTED_SKIP_REASONS for skipped in result.meta.skipped_files)


def _degraded_reason(result: AggregatorOutput) -> str:
    failed_agent_files = [entry.file_path for entry in result.review if entry.agents_failed]
    failed_whole_files = [
        skipped.file_path for skipped in result.meta.skipped_files if skipped.reason in _UNEXPECTED_SKIP_REASONS
    ]
    return f"agents_failed on files={failed_agent_files}; files_skipped_on_failure={failed_whole_files}"
