"""
    The cap on a user's unfinished reviews against the real local Postgres, including the race it exists for:
    many simultaneous requests from one user for the last free slots.

    Like the OAuth refresh race test, this commits real rows through separate connections and deletes them at
    the end. Requires the migrations to have been applied (`alembic upgrade head`).
"""
import asyncio
import time
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.config.settings import get_api_settings
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.review.errors import ReviewSlotBusyError, TooManyUnfinishedReviewsError
from api.review.review_capacity import ReviewSlotKeeper, unfinished_reviews_count_statement

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

LIMIT = 3
ATTEMPTS = 12
BUSY_USER_GITHUB_ID = 940_000_101
OTHER_USER_GITHUB_ID = 940_000_102
TEST_GITHUB_IDS = (BUSY_USER_GITHUB_ID, OTHER_USER_GITHUB_ID)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(get_api_settings().async_database_url, pool_size=ATTEMPTS + 2)
    yield test_engine
    async with async_sessionmaker(test_engine)() as cleanup_session:
        test_user_ids = select(User.id).where(User.github_id.in_(TEST_GITHUB_IDS))
        await cleanup_session.execute(delete(ReviewJob).where(ReviewJob.requested_by_user_id.in_(test_user_ids)))
        await cleanup_session.execute(delete(User).where(User.github_id.in_(TEST_GITHUB_IDS)))
        await cleanup_session.commit()
    await test_engine.dispose()


async def _create_user(engine: AsyncEngine, github_id: int) -> int:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user = User(
            github_id=github_id,
            github_username=f"slot-test-{github_id}",
            encrypted_github_token="unused",
            github_granted_scopes="repo",
        )
        session.add(user)
        await session.commit()
        return user.id


def _job(user_id: int, status: ReviewJobStatus = ReviewJobStatus.PENDING) -> ReviewJob:
    return ReviewJob(review_id=uuid.uuid4(), requested_by_user_id=user_id, file_paths=[], status=status)


async def _store_jobs(engine: AsyncEngine, user_id: int, statuses: list[ReviewJobStatus]) -> None:
    async with async_sessionmaker(engine)() as session:
        session.add_all(_job(user_id, status) for status in statuses)
        await session.commit()


async def _count_stored_jobs(engine: AsyncEngine, user_id: int) -> int:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(ReviewJob).where(ReviewJob.requested_by_user_id == user_id))


async def _count_unfinished(engine: AsyncEngine, user_id: int) -> int:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(unfinished_reviews_count_statement(user_id))


async def _try_to_start_a_review(engine: AsyncEngine, user_id: int, barrier: asyncio.Barrier) -> bool:
    """One request: reserve the slot, store the job, commit. Returns whether it got a slot."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await barrier.wait()
        try:
            await ReviewSlotKeeper(session, LIMIT).reserve(user_id)
        except TooManyUnfinishedReviewsError:
            await session.rollback()
            return False
        session.add(_job(user_id))
        await session.commit()
        return True


async def _try_to_start_a_review_without_the_lock(engine: AsyncEngine, user_id: int, barrier: asyncio.Barrier) -> bool:
    """The same request with only the early check: every request checks before any of them has inserted."""
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        try:
            await ReviewSlotKeeper(session, LIMIT).ensure_capacity(user_id)
        except TooManyUnfinishedReviewsError:
            await session.rollback()
            return False
        await barrier.wait()
        session.add(_job(user_id))
        await session.commit()
        return True


async def test_many_simultaneous_requests_never_take_more_slots_than_the_limit(engine: AsyncEngine) -> None:
    """Verify the lock makes the check and the insert atomic: of 12 requests at once, exactly 3 get a slot."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    barrier = asyncio.Barrier(ATTEMPTS)

    results = await asyncio.gather(*(_try_to_start_a_review(engine, user_id, barrier) for _ in range(ATTEMPTS)))

    assert results.count(True) == LIMIT


async def test_the_jobs_stored_after_the_race_are_exactly_the_limit(engine: AsyncEngine) -> None:
    """Verify the database, not just the return values, ends with the limit and no more."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    barrier = asyncio.Barrier(ATTEMPTS)

    await asyncio.gather(*(_try_to_start_a_review(engine, user_id, barrier) for _ in range(ATTEMPTS)))

    assert await _count_stored_jobs(engine, user_id) == LIMIT


async def test_without_the_lock_simultaneous_requests_exceed_the_limit(engine: AsyncEngine) -> None:
    """Control: with only the early check every request passes it, proving the race is real and the test sees it."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    barrier = asyncio.Barrier(ATTEMPTS)

    results = await asyncio.gather(
        *(_try_to_start_a_review_without_the_lock(engine, user_id, barrier) for _ in range(ATTEMPTS))
    )

    assert results.count(True) > LIMIT


async def test_a_request_that_cannot_get_the_slot_lock_in_time_is_refused_instead_of_waiting(
    engine: AsyncEngine,
) -> None:
    """Verify a real Postgres lock timeout becomes a clean refusal, and quickly, while another request holds the lock."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    async with async_sessionmaker(engine)() as holder, async_sessionmaker(engine)() as waiter:
        await ReviewSlotKeeper(holder, LIMIT).reserve(user_id)
        started = time.monotonic()

        with pytest.raises(ReviewSlotBusyError):
            await ReviewSlotKeeper(waiter, LIMIT, lock_timeout_seconds=1).reserve(user_id)

        waited = time.monotonic() - started
        await holder.rollback()
    assert 0.9 <= waited < 3


async def test_a_request_that_waits_for_the_lock_counts_the_job_the_holder_committed(engine: AsyncEngine) -> None:
    """Verify a holder that commits within the timeout releases the waiter, which then sees the job and is refused."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    await _store_jobs(engine, user_id, [ReviewJobStatus.PENDING] * (LIMIT - 1))
    holder_session = async_sessionmaker(engine, expire_on_commit=False)()
    await ReviewSlotKeeper(holder_session, LIMIT).reserve(user_id)

    async def commit_the_holders_job_soon() -> None:
        await asyncio.sleep(0.5)
        holder_session.add(_job(user_id))
        await holder_session.commit()
        await holder_session.close()

    async def waiting_request() -> None:
        async with async_sessionmaker(engine)() as session:
            await ReviewSlotKeeper(session, LIMIT, lock_timeout_seconds=5).reserve(user_id)

    results = await asyncio.gather(commit_the_holders_job_soon(), waiting_request(), return_exceptions=True)

    assert isinstance(results[1], TooManyUnfinishedReviewsError)


async def test_one_users_requests_never_use_up_another_users_slots(engine: AsyncEngine) -> None:
    """Verify each user has their own limit, and one user's lock does not make another user wait."""
    busy_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    other_id = await _create_user(engine, OTHER_USER_GITHUB_ID)
    await _store_jobs(engine, busy_id, [ReviewJobStatus.PENDING] * LIMIT)

    async with async_sessionmaker(engine)() as session:
        assert await ReviewSlotKeeper(session, LIMIT).reserve(other_id) is None


async def test_a_user_at_the_limit_is_refused(engine: AsyncEngine) -> None:
    """Verify the authoritative check refuses against real rows."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    await _store_jobs(engine, user_id, [ReviewJobStatus.PENDING, ReviewJobStatus.RUNNING, ReviewJobStatus.PENDING])

    async with async_sessionmaker(engine)() as session:
        with pytest.raises(TooManyUnfinishedReviewsError):
            await ReviewSlotKeeper(session, LIMIT).reserve(user_id)


async def test_only_pending_and_running_reviews_count_as_unfinished(engine: AsyncEngine) -> None:
    """Verify, against the real enum column, that finished reviews do not hold a slot."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    statuses = [
        ReviewJobStatus.PENDING,
        ReviewJobStatus.RUNNING,
        ReviewJobStatus.COMPLETED,
        ReviewJobStatus.COMPLETED,
        ReviewJobStatus.FAILED,
    ]
    await _store_jobs(engine, user_id, statuses)

    assert await _count_unfinished(engine, user_id) == 2


async def test_a_finished_review_frees_its_slot(engine: AsyncEngine) -> None:
    """Verify a user at the limit can start another review as soon as one of theirs finishes."""
    user_id = await _create_user(engine, BUSY_USER_GITHUB_ID)
    await _store_jobs(engine, user_id, [ReviewJobStatus.PENDING] * LIMIT)
    async with async_sessionmaker(engine)() as session:
        job = (await session.scalars(select(ReviewJob).where(ReviewJob.requested_by_user_id == user_id))).first()
        job.status = ReviewJobStatus.COMPLETED
        await session.commit()

    async with async_sessionmaker(engine)() as session:
        assert await ReviewSlotKeeper(session, LIMIT).reserve(user_id) is None
