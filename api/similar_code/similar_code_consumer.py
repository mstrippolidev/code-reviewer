"""
    Concrete consumer class for similar-code.requested: checks one stored snippet
    against a repo's indexed history and records the outcome on its row.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from aiokafka import AIOKafkaConsumer, ConsumerRecord
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.similar_code_search import SimilarCodeSearch, SimilarCodeSearchStatus
from api.indexing.consumers.interface import ConsumerInterface
from api.observability.clock import seconds_since
from api.observability.metrics import api_metrics
from api.schemas.similar_code import SimilarCodeRequestedMessage
from api.similar_code.topics import SIMILAR_CODE_REQUESTED
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.guardrails.errors import GuardrailsInvocationError, IntakeRejectedError
from code_reviewer.pipeline.dry_check import check_snippet_for_duplicates
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.rag.dry_judge import DryJudgeInvocationError
from code_reviewer.rag.errors import (
    ChunkExplanationError,
    DryMatchingChunkingError,
    StructuralIndexQueryError,
    VectorStoreQueryError,
)
from code_reviewer.rag.repo_data import RepoData

logger = logging.getLogger(__name__)

GROUP_ID = "similar_code_request_consumer"
INTAKE_REJECTED_DETAIL = "The snippet was rejected: it is not source code, or it contains instructions aimed at the reviewer"
CHUNKING_FAILED_DETAIL = "The snippet could not be split into functions or classes. Send complete Python code"
SEARCH_UNAVAILABLE_DETAIL = "Could not check this snippet against the repo"

_REFUSED_SNIPPET_ERRORS = (SubmissionTooLargeError, FileTooLargeError, IntakeRejectedError, DryMatchingChunkingError)
_UNAVAILABLE_SEARCH_ERRORS = (
    VectorStoreQueryError,
    StructuralIndexQueryError,
    ChunkExplanationError,
    DryJudgeInvocationError,
    GuardrailsInvocationError,
    TimeoutError,
)
_FINAL_STATUSES = frozenset(
    {SimilarCodeSearchStatus.COMPLETED, SimilarCodeSearchStatus.REJECTED, SimilarCodeSearchStatus.FAILED}
)


class SimilarCodeMessageParseError(Exception):
    """Raised when a similar-code.requested message cannot be parsed into a SimilarCodeRequestedMessage."""


class SimilarCodeSearchUnavailableError(Exception):
    """Raised when a requested search or its repo no longer has a row."""


@dataclass(frozen=True)
class SimilarCodeConsumerDependencies:
    """Collaborators SimilarCodeRequestConsumer needs to run one search end to end."""

    database_engine: DatabaseEngine
    agents_container: AgentsContainer


@dataclass(frozen=True)
class _Outcome:
    """How one search ended: its final status, why (for a refusal or failure), and the incidents (for a success)."""

    status: SimilarCodeSearchStatus
    reason: str | None = None
    incidents: list[dict] | None = None


class SimilarCodeRequestConsumer(ConsumerInterface[SimilarCodeRequestedMessage]):
    """Consumes similar-code.requested and runs DRY's history workflow for one stored snippet."""

    def __init__(self, dependencies: SimilarCodeConsumerDependencies) -> None:
        bootstrap_servers = get_api_settings().kafka_bootstrap_servers
        super().__init__(SIMILAR_CODE_REQUESTED, bootstrap_servers, GROUP_ID, enable_auto_commit=False)
        self._dependencies = dependencies

    def _parse_msg(self, msg: ConsumerRecord) -> SimilarCodeRequestedMessage:
        """Turns the raw Kafka record into a SimilarCodeRequestedMessage, or raises if it is malformed."""
        try:
            return SimilarCodeRequestedMessage.model_validate_json(msg.value)
        except ValidationError as error:
            raise SimilarCodeMessageParseError("Could not parse similar-code.requested message") from error

    async def _handle_parse_error(self, msg: ConsumerRecord, error: Exception) -> None:
        """Logs a malformed message and moves on; there is no search row to update and no dead-letter topic."""
        logger.error("Could not parse similar-code.requested message at offset=%s", msg.offset, exc_info=error)

    async def _handle_parsed_message(
        self, message: SimilarCodeRequestedMessage, msg: ConsumerRecord, consumer: AIOKafkaConsumer
    ) -> None:
        """Runs the search, and if anything unexpected goes wrong marks the search failed so a poller is not left waiting."""
        try:
            await self._run_search(message)
        except Exception:
            logger.exception("Failed to process similar-code.requested for search_id=%s", message.search_id)
            await self._mark_failed_best_effort(message.search_id)

    async def _run_search(self, message: SimilarCodeRequestedMessage) -> None:
        """Runs one search from `running` to its final status; a search that already finished is left alone."""
        async with self._dependencies.database_engine.new_session() as session:
            search = await self._load_search(message.search_id, session)
            if search.status in _FINAL_STATUSES:
                return
            search.status = SimilarCodeSearchStatus.RUNNING
            await session.commit()
            api_metrics.record_search_started(seconds_since(search.created_at))
            repo_data = await self._load_repo_data(message.repo_id, session)
            started = time.perf_counter()
            outcome = await self._check(repo_data, search.code)
            api_metrics.record_search_checked(outcome.status, time.perf_counter() - started)
            await self._finish(search, outcome, session)

    async def _check(self, repo_data: RepoData, code: str) -> _Outcome:
        """Runs the duplicate check off the event loop and turns its result or known failure into an outcome."""
        try:
            entry = await asyncio.to_thread(
                check_snippet_for_duplicates, self._dependencies.agents_container, repo_data, code
            )
        except _REFUSED_SNIPPET_ERRORS as error:
            return _Outcome(SimilarCodeSearchStatus.REJECTED, reason=_refusal_detail(error))
        except _UNAVAILABLE_SEARCH_ERRORS:
            logger.error("similar-code search failed repo_id=%s", repo_data.repo_id, exc_info=True)
            return _Outcome(SimilarCodeSearchStatus.FAILED, reason=SEARCH_UNAVAILABLE_DETAIL)
        incidents = [incident.model_dump(mode="json") for incident in entry.incidents]
        return _Outcome(SimilarCodeSearchStatus.COMPLETED, incidents=incidents)

    async def _finish(self, search: SimilarCodeSearch, outcome: _Outcome, session: AsyncSession) -> None:
        """Saves the outcome on the search row and deletes the stored snippet, which is no longer needed."""
        search.status = outcome.status
        search.status_reason = outcome.reason
        search.incidents = outcome.incidents
        search.code = None
        search.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await session.commit()
        api_metrics.record_search_finished(outcome.status)

    async def _load_search(self, search_id: UUID, session: AsyncSession) -> SimilarCodeSearch:
        """Reads the search row, or raises if it does not exist."""
        search = await session.scalar(select(SimilarCodeSearch).where(SimilarCodeSearch.search_id == search_id))
        if search is None:
            raise SimilarCodeSearchUnavailableError(f"No SimilarCodeSearch row for search_id={search_id}")
        return search

    async def _load_repo_data(self, repo_id: int, session: AsyncSession) -> RepoData:
        """Builds the repo scoping (repo, owner, commit) the duplicate check searches within, or raises if the repo is gone."""
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None:
            raise SimilarCodeSearchUnavailableError(f"No RegisteredRepo row for repo_id={repo_id}")
        return RepoData(repo_id=str(repo.repo_id), owner_id=str(repo.owner_id), commit_sha=repo.commit_sha)

    async def _mark_failed_best_effort(self, search_id: UUID) -> None:
        """After an unexpected crash, tries to set the search to `failed` so whoever polls it stops waiting.

        Never raises: if this recovery step itself fails (for example the database is down), it only logs.
        A search that already reached a final status is left as it is.
        """
        try:
            async with self._dependencies.database_engine.new_session() as session:
                search = await session.scalar(select(SimilarCodeSearch).where(SimilarCodeSearch.search_id == search_id))
                if search is None or search.status in _FINAL_STATUSES:
                    return
                await self._finish(search, _Outcome(SimilarCodeSearchStatus.FAILED, SEARCH_UNAVAILABLE_DETAIL), session)
        except Exception:
            logger.exception("Could not mark search_id=%s FAILED after an earlier failure", search_id)


def _refusal_detail(error: Exception) -> str:
    """The message shown to the caller for a refused snippet; guardrail internals are replaced by a fixed text."""
    if isinstance(error, IntakeRejectedError):
        logger.warning("similar-code snippet rejected by the intake screen: %s", error)
        return INTAKE_REJECTED_DETAIL
    if isinstance(error, DryMatchingChunkingError):
        return CHUNKING_FAILED_DETAIL
    return str(error)
