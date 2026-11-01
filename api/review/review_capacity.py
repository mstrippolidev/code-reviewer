"""
    Caps how many reviews one user can have unfinished at once, so a backlog of long reviews cannot pile up behind
    the single worker and delay everyone else's. Counted in Postgres, so it holds across API replicas.
"""
from fastapi import Depends
from sqlalchemy import Select, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.review.errors import ReviewSlotBusyError, TooManyUnfinishedReviewsError

UNFINISHED_STATUSES = (ReviewJobStatus.PENDING, ReviewJobStatus.RUNNING)
REVIEW_SLOT_LOCK_NAMESPACE = 0x52455649
DEFAULT_LOCK_TIMEOUT_SECONDS = 5
LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"


def unfinished_reviews_count_statement(user_id: int) -> Select:
    """The query counting a user's reviews that have not finished, a pull request waiting on its index included."""
    return (
        select(func.count())
        .select_from(ReviewJob)
        .where(ReviewJob.requested_by_user_id == user_id, ReviewJob.status.in_(UNFINISHED_STATUSES))
    )


class ReviewSlotKeeper:
    """Decides whether a user may start another review."""

    def __init__(
        self, session: AsyncSession, limit: int, lock_timeout_seconds: int = DEFAULT_LOCK_TIMEOUT_SECONDS
    ) -> None:
        self._session = session
        self._limit = limit
        self._lock_timeout = f"{lock_timeout_seconds * 1000}ms"

    async def ensure_capacity(self, user_id: int) -> None:
        """Refuses if the user is at the limit right now. Cheap, but a concurrent request can still slip past it.

        Raises:
            TooManyUnfinishedReviewsError: If the user is at or over the limit.
        """
        unfinished = await self._session.scalar(unfinished_reviews_count_statement(user_id))
        if unfinished >= self._limit:
            raise TooManyUnfinishedReviewsError(self._limit)

    async def reserve(self, user_id: int) -> None:
        """Takes the user's slot lock, then refuses if they are at the limit; the caller must then add its job.

        The lock lasts until the session's transaction ends, so the caller has to add the review job and commit
        straight away, with nothing slow in between (no GitHub, Kafka or LLM call): every other review request
        from the same user waits here for that time, which has to stay in the milliseconds. Once it commits, the
        next request counts the job just added, so two simultaneous requests can never both take the last slot.

        Waiting for the lock is capped by a Postgres lock timeout (5 seconds by default), well above how long a
        holder should take, so a stuck holder makes this request fail fast instead of piling requests up.

        Raises:
            TooManyUnfinishedReviewsError: If the user is at or over the limit.
            ReviewSlotBusyError: If the user's lock could not be taken within the timeout.
        """
        try:
            await self._session.execute(select(func.set_config("lock_timeout", self._lock_timeout, True)))
            await self._session.execute(select(func.pg_advisory_xact_lock(REVIEW_SLOT_LOCK_NAMESPACE, user_id)))
        except DBAPIError as error:
            if _is_lock_timeout(error):
                raise ReviewSlotBusyError() from error
            raise
        await self.ensure_capacity(user_id)


def _is_lock_timeout(error: DBAPIError) -> bool:
    """Whether Postgres gave up waiting for a lock (SQLSTATE 55P03), as opposed to any other database error."""
    return getattr(error.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE_SQLSTATE


def get_review_slot_keeper(session: AsyncSession = Depends(get_db_session)) -> ReviewSlotKeeper:
    """The slot keeper for one request, sharing the request's database session."""
    return ReviewSlotKeeper(session, get_api_settings().max_unfinished_reviews_per_user)


async def require_review_capacity(
    current_user: User = Depends(get_current_user),
    slot_keeper: ReviewSlotKeeper = Depends(get_review_slot_keeper),
) -> None:
    """Route-level early refusal for a user at the limit, before any expensive work such as reading GitHub."""
    await slot_keeper.ensure_capacity(current_user.id)
