"""
    Shared method to ask if the file was process or not and their status
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.indexing.producer import RepoIndexProducer
from api.indexing.topics import REPO_STATUS_PROGRESS
from api.observability.metrics import api_metrics
from api.review.pull_request_release import PendingPullRequestReleaser
from api.schemas.repos import RepoStatusProgressMessage

logger = logging.getLogger(__name__)


_TERMINAL_FILE_STATUSES = (IndexedFileStatus.INDEXED, IndexedFileStatus.SKIPPED, IndexedFileStatus.FAILED)


class RepoCompletionFinalizer:
    """Marks a repo COMPLETED or FAILED once every expected file reaches a terminal status; safe under concurrent callers."""

    def __init__(self, producer: RepoIndexProducer, pull_request_releaser: PendingPullRequestReleaser | None = None) -> None:
        self._producer = producer
        self._pull_request_releaser = pull_request_releaser or PendingPullRequestReleaser(producer)

    async def finalize_if_complete(self, repo_id: int, session: AsyncSession) -> None:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None or repo.total_files_expected is None:
            return
        status_counts = await self._count_files_by_status(repo_id, session)
        terminal_count = sum(status_counts[status] for status in _TERMINAL_FILE_STATUSES)
        if terminal_count < repo.total_files_expected:
            return
        final_status, status_reason = self._resolve_final_status(status_counts)
        result = await session.execute(
            update(RegisteredRepo)
            .where(RegisteredRepo.repo_id == repo_id, RegisteredRepo.status == RepoIndexStatus.INDEXING)
            .values(status=final_status, status_reason=status_reason)
        )
        await session.commit()
        if result.rowcount == 0:
            return  # another caller already finalized it — the WHERE just protected us from a double-fire
        api_metrics.record_repo_finished(final_status, status_counts)
        await self._publish_final_status(repo_id, repo.total_files_expected, final_status, status_reason)
        await self._settle_pull_request_reviews(repo, final_status, session)

    async def fail_pull_request_reviews(self, repo_id: int, session: AsyncSession) -> None:
        """Fails the pull request reviews waiting on a repo whose indexing failed outright; never raises, only logs."""
        try:
            await self._pull_request_releaser.fail(repo_id, session)
        except Exception:
            logger.exception("Failed to fail the pull request reviews waiting on repo_id=%s", repo_id)

    async def _settle_pull_request_reviews(
        self, repo: RegisteredRepo, final_status: RepoIndexStatus, session: AsyncSession
    ) -> None:
        """Starts the pull request reviews waiting on this repo if it completed, or fails them if it did not.

        Never raises: the repo's status is already committed, and a problem settling reviews must not undo or
        hide that.
        """
        try:
            if final_status == RepoIndexStatus.COMPLETED:
                await self._pull_request_releaser.release(repo, session)
            else:
                await self._pull_request_releaser.fail(repo.repo_id, session)
        except Exception:
            logger.exception("Failed to settle the pull request reviews waiting on repo_id=%s", repo.repo_id)

    async def _count_files_by_status(self, repo_id: int, session: AsyncSession) -> dict[IndexedFileStatus, int]:
        rows = await session.execute(
            select(IndexedFile.status, func.count())
            .where(IndexedFile.repo_id == repo_id)
            .group_by(IndexedFile.status)
        )
        counts = dict(rows.all())
        return {status: counts.get(status, 0) for status in IndexedFileStatus}

    def _resolve_final_status(self, status_counts: dict[IndexedFileStatus, int]) -> tuple[RepoIndexStatus, str | None]:
        indexed_count = status_counts[IndexedFileStatus.INDEXED]
        failed_count = status_counts[IndexedFileStatus.FAILED]
        if indexed_count == 0 and failed_count > 0:
            return RepoIndexStatus.FAILED, f"All {failed_count} processed files failed to index"
        return RepoIndexStatus.COMPLETED, None

    async def _publish_final_status(
        self, repo_id: int, total_files_expected: int, final_status: RepoIndexStatus, status_reason: str | None
    ) -> None:
        try:
            await self._producer.publish(
                REPO_STATUS_PROGRESS,
                RepoStatusProgressMessage(
                    repo_id=repo_id,
                    status=final_status,
                    status_reason=status_reason,
                    total_files_expected=total_files_expected,
                ),
                str(repo_id).encode(),
            )
        except Exception:
            # A lost notification, not a lost result — RegisteredRepo.status is already committed.
            logger.exception("Failed to publish repo.status.progress for repo_id=%s", repo_id)
