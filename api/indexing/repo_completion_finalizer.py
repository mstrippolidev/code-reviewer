"""
    Shared method to ask if the file was process or not and their status
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.indexing.producer import RepoIndexProducer
from api.indexing.topics import REPO_STATUS_PROGRESS
from api.schemas.repos import RepoStatusProgressMessage


class RepoCompletionFinalizer:
    """Marks a repo indexed once every expected file reaches a terminal status; safe under concurrent callers."""

    def __init__(self, producer: RepoIndexProducer) -> None:
        self._producer = producer

    async def finalize_if_complete(self, repo_id: int, session: AsyncSession) -> None:
        repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
        if repo is None or repo.total_files_expected is None:
            return
        terminal_count = await session.scalar(
            select(func.count()).select_from(IndexedFile).where(
                IndexedFile.repo_id == repo_id,
                IndexedFile.status.in_(
                    [IndexedFileStatus.INDEXED, IndexedFileStatus.SKIPPED, IndexedFileStatus.FAILED]
                ),
            )
        )
        if terminal_count < repo.total_files_expected:
            return
        result = await session.execute(
            update(RegisteredRepo)
            .where(RegisteredRepo.repo_id == repo_id, RegisteredRepo.status == RepoIndexStatus.INDEXING)
            .values(status=RepoIndexStatus.INDEXED)
        )
        await session.commit()
        if result.rowcount == 0:
            return  # another caller already finalized it — the WHERE just protected us from a double-fire
        await self._producer.publish(
            REPO_STATUS_PROGRESS,
            RepoStatusProgressMessage(repo_id=repo_id, status=RepoIndexStatus.INDEXED, status_reason=None),
            str(repo_id).encode(),
        )
