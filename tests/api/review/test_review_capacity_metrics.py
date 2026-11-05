"""
    Tests that the review slot keeper reports how close a user is to the cap and every refusal it makes.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy.exc import DBAPIError

from api.observability.metrics import ApiMetrics
from api.review import review_capacity
from api.review.errors import ReviewSlotBusyError, TooManyUnfinishedReviewsError
from api.review.review_capacity import ReviewSlotKeeper
from tests.api.review.test_review_capacity import LIMIT, USER, FakeCountSession, FakeDatabaseError, _keeper
from tests.metric_points import GUARD_REFUSALS, GUARD_UNFINISHED_REVIEWS, point_with, points_for

_GUARD = "code_reviewer.guard"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the keeper at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(review_capacity, "api_metrics", isolated_api_metrics)


@pytest.mark.asyncio
async def test_every_check_records_how_many_reviews_the_user_had_unfinished(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the cap check reports its count, so the spread of how close users get is visible."""
    keeper, _session = _keeper(2)

    await keeper.ensure_capacity(USER.id)

    assert points_for(metric_reader, GUARD_UNFINISHED_REVIEWS)[0].sum == 2


@pytest.mark.asyncio
async def test_a_user_with_room_records_no_refusal(metric_reader: InMemoryMetricReader) -> None:
    """Verify an admitted request is not counted as a refusal."""
    keeper, _session = _keeper(LIMIT - 1)

    await keeper.ensure_capacity(USER.id)

    assert points_for(metric_reader, GUARD_REFUSALS) == []


@pytest.mark.asyncio
async def test_a_user_at_the_limit_is_counted_as_refused_and_still_raises(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the cap refusal is counted under its guard, and the error the route turns into a 429 still propagates."""
    keeper, _session = _keeper(LIMIT)

    with pytest.raises(TooManyUnfinishedReviewsError):
        await keeper.ensure_capacity(USER.id)

    assert point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "unfinished_reviews"}).value == 1
    assert points_for(metric_reader, GUARD_UNFINISHED_REVIEWS)[0].sum == LIMIT


@pytest.mark.asyncio
async def test_reserving_at_the_limit_is_counted_once_as_a_refusal(metric_reader: InMemoryMetricReader) -> None:
    """Verify the authoritative check counts its own refusal, once."""
    keeper, _session = _keeper(LIMIT)

    with pytest.raises(TooManyUnfinishedReviewsError):
        await keeper.reserve(USER.id)

    assert point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "unfinished_reviews"}).value == 1


@pytest.mark.asyncio
async def test_a_lock_timeout_is_counted_as_a_busy_slot_not_as_a_full_cap(metric_reader: InMemoryMetricReader) -> None:
    """Verify a stuck slot lock is its own guard, since it points at infrastructure rather than at the user."""
    session = FakeCountSession(0, lock_error=DBAPIError("SELECT", {}, FakeDatabaseError("55P03")))

    with pytest.raises(ReviewSlotBusyError):
        await ReviewSlotKeeper(session, LIMIT).reserve(USER.id)

    assert point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "review_slot_busy"}).value == 1
    assert points_for(metric_reader, GUARD_UNFINISHED_REVIEWS) == []


@pytest.mark.asyncio
async def test_a_database_error_that_is_not_a_lock_timeout_is_not_counted_as_a_refusal(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify a real database failure is not reported as a guard doing its job."""
    session = FakeCountSession(0, lock_error=DBAPIError("SELECT", {}, FakeDatabaseError("08006")))

    with pytest.raises(DBAPIError):
        await ReviewSlotKeeper(session, LIMIT).reserve(USER.id)

    assert points_for(metric_reader, GUARD_REFUSALS) == []
