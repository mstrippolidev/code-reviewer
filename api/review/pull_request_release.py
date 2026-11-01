"""
    Starts, or fails, the pull request reviews that were waiting for their repo to finish indexing.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.registered_repo import RegisteredRepo
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.indexing.producer import PublishError, RepoIndexProducer
from api.review.pull_request_queue import NOT_QUEUED_REASON, publish_pull_request_review

logger = logging.getLogger(__name__)

INDEX_FAILED_REASON = "Indexing the repo failed, so the pull request could not be reviewed"


class PendingPullRequestReleaser:
    """Settles the pending pull request reviews of a repo once its indexing has reached a final status."""

    def __init__(self, producer: RepoIndexProducer) -> None:
        self._producer = producer

    async def release(self, repo: RegisteredRepo, session: AsyncSession) -> None:
        """Publishes every pending pull request review of the repo, now that its index is complete.

        A review that was already published and is still queued is published a second time; the worker skips a
        review that has already finished, so the duplicate costs nothing. A review whose message cannot be
        published is failed instead of being left pending.
        """
        for job in await self._pending_pull_request_jobs(repo.repo_id, session):
            job.status_reason = None
            await self._publish_or_fail(job, repo)
        await session.commit()

    async def fail(self, repo_id: int, session: AsyncSession) -> None:
        """Fails every pending pull request review of the repo, since its indexing failed."""
        for job in await self._pending_pull_request_jobs(repo_id, session):
            job.status = ReviewJobStatus.FAILED
            job.status_reason = INDEX_FAILED_REASON
        await session.commit()

    async def _pending_pull_request_jobs(self, repo_id: int, session: AsyncSession) -> list[ReviewJob]:
        """The repo's pull request reviews that have not started."""
        result = await session.scalars(
            select(ReviewJob).where(
                ReviewJob.repo_id == repo_id,
                ReviewJob.status == ReviewJobStatus.PENDING,
                ReviewJob.pr_number.is_not(None),
            )
        )
        return list(result.all())

    async def _publish_or_fail(self, job: ReviewJob, repo: RegisteredRepo) -> None:
        """Sends one job to the worker, or marks it failed if Kafka refuses it."""
        try:
            await publish_pull_request_review(self._producer, job, repo)
        except PublishError:
            logger.error("Could not publish pull request review %s after indexing", job.review_id, exc_info=True)
            job.status = ReviewJobStatus.FAILED
            job.status_reason = NOT_QUEUED_REASON
