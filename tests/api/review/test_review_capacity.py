"""
    The cap on a user's unfinished reviews: the slot keeper against a fake session, the SQL it sends, and that
    every submit route is behind it. Its behavior against a real Postgres is in tests/api/db/test_review_slots.py.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from api.config.settings import get_api_settings
from api.db.models.user import User
from api.dependencies import get_current_user
from api.exception_handlers import register_exception_handlers
from api.review.errors import ReviewSlotBusyError, TooManyUnfinishedReviewsError
from api.review.review_capacity import (
    REVIEW_SLOT_LOCK_NAMESPACE,
    ReviewSlotKeeper,
    get_review_slot_keeper,
    require_review_capacity,
    unfinished_reviews_count_statement,
)
from api.routers import pull_requests, reviews
from api.security.rate_limit_dependencies import get_rate_limiter
from tests.api.fake_rate_limit import AllowAllRateLimiter
from tests.api.fake_review_slots import FakeSlotKeeper

LIMIT = get_api_settings().max_unfinished_reviews_per_user
USER = User(id=7, encrypted_github_token="unused")


class FakeDatabaseError(Exception):
    """Stands in for the driver's error, carrying the SQLSTATE Postgres reported."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class FakeCountSession:
    """Answers the count query with a canned number, and remembers the order of the timeout, the lock and the count."""

    def __init__(self, unfinished: int, lock_error: Exception | None = None) -> None:
        self._unfinished = unfinished
        self._lock_error = lock_error
        self.calls: list[str] = []
        self.statements: dict[str, str] = {}

    async def execute(self, statement) -> None:
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        name = "timeout" if "set_config" in sql else "lock"
        self.calls.append(name)
        self.statements[name] = sql
        if name == "lock" and self._lock_error:
            raise self._lock_error

    async def scalar(self, statement) -> int:
        self.calls.append("count")
        return self._unfinished


def _keeper(unfinished: int) -> tuple[ReviewSlotKeeper, FakeCountSession]:
    session = FakeCountSession(unfinished)
    return ReviewSlotKeeper(session, LIMIT), session


@pytest.mark.asyncio
@pytest.mark.parametrize("unfinished", [0, LIMIT - 1])
async def test_a_user_below_the_limit_may_start_a_review(unfinished: int) -> None:
    """Verify a user with room is not blocked, from the first review up to the last free slot."""
    keeper, _session = _keeper(unfinished)

    assert await keeper.ensure_capacity(USER.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("unfinished", [LIMIT, LIMIT + 2])
async def test_a_user_at_or_over_the_limit_is_refused(unfinished: int) -> None:
    """Verify the limit is the number of unfinished reviews allowed, so one more is refused."""
    keeper, _session = _keeper(unfinished)

    with pytest.raises(TooManyUnfinishedReviewsError):
        await keeper.ensure_capacity(USER.id)


@pytest.mark.asyncio
async def test_the_early_check_takes_no_lock() -> None:
    """Verify the cheap check made at the top of a route never serializes a user's requests."""
    keeper, session = _keeper(0)

    await keeper.ensure_capacity(USER.id)

    assert session.calls == ["count"]


@pytest.mark.asyncio
async def test_reserving_sets_the_timeout_then_takes_the_lock_then_counts() -> None:
    """Verify the count is made while holding the lock, and the wait for the lock is already capped when it is taken."""
    keeper, session = _keeper(0)

    await keeper.reserve(USER.id)

    assert session.calls == ["timeout", "lock", "count"]


@pytest.mark.asyncio
async def test_the_lock_wait_is_capped_at_five_seconds_by_default() -> None:
    """Verify a stuck holder cannot make other requests from the same user wait longer than that."""
    keeper, session = _keeper(0)

    await keeper.reserve(USER.id)

    assert "set_config('lock_timeout', '5000ms', true)" in session.statements["timeout"]


@pytest.mark.asyncio
async def test_the_lock_wait_cap_applies_only_to_the_current_transaction() -> None:
    """Verify the timeout is transaction-local, so it never leaks onto the pooled connection's next request."""
    keeper, session = _keeper(0)

    await keeper.reserve(USER.id)

    assert "'5000ms', true)" in session.statements["timeout"]


@pytest.mark.asyncio
async def test_the_lock_is_per_user_and_namespaced() -> None:
    """Verify one user's requests never wait on another's, and the key cannot collide with other advisory locks."""
    keeper, session = _keeper(0)

    await keeper.reserve(USER.id)

    assert f"pg_advisory_xact_lock({REVIEW_SLOT_LOCK_NAMESPACE}, {USER.id})" in session.statements["lock"]


@pytest.mark.asyncio
async def test_a_lock_the_database_gave_up_waiting_for_is_reported_as_the_user_being_busy() -> None:
    """Verify Postgres' lock-timeout error (SQLSTATE 55P03) becomes a clear refusal, not an unhandled database error."""
    error = DBAPIError("SELECT", {}, FakeDatabaseError("55P03"))
    session = FakeCountSession(0, lock_error=error)

    with pytest.raises(ReviewSlotBusyError):
        await ReviewSlotKeeper(session, LIMIT).reserve(USER.id)


@pytest.mark.asyncio
async def test_any_other_database_error_while_locking_is_not_disguised_as_busy() -> None:
    """Verify only the lock timeout is translated, so a real database failure is never reported as a busy user."""
    error = DBAPIError("SELECT", {}, FakeDatabaseError("08006"))
    session = FakeCountSession(0, lock_error=error)

    with pytest.raises(DBAPIError):
        await ReviewSlotKeeper(session, LIMIT).reserve(USER.id)


@pytest.mark.asyncio
async def test_a_busy_user_is_never_counted_after_the_lock_timed_out() -> None:
    """Verify a request that could not take the lock does not go on to count and insert without it."""
    session = FakeCountSession(0, lock_error=DBAPIError("SELECT", {}, FakeDatabaseError("55P03")))

    with pytest.raises(ReviewSlotBusyError):
        await ReviewSlotKeeper(session, LIMIT).reserve(USER.id)

    assert "count" not in session.calls


@pytest.mark.asyncio
async def test_reserving_at_the_limit_is_refused() -> None:
    """Verify the authoritative check refuses the request that lost the race for the last slot."""
    keeper, _session = _keeper(LIMIT)

    with pytest.raises(TooManyUnfinishedReviewsError):
        await keeper.reserve(USER.id)


@pytest.mark.asyncio
async def test_the_route_level_check_uses_the_early_check_for_the_caller() -> None:
    """Verify the dependency asks about the authenticated user, without reserving anything."""
    slot_keeper = FakeSlotKeeper()

    await require_review_capacity(USER, slot_keeper)

    assert (slot_keeper.checked, slot_keeper.reserved) == ([USER.id], [])


def test_the_refusal_tells_the_user_the_limit_and_what_to_do() -> None:
    """Verify the message names the limit and says to wait, since the MCP tools show it to the model."""
    message = str(TooManyUnfinishedReviewsError(3))

    assert "3 reviews" in message and "Wait for one to finish" in message


def _sql_of_the_count_query() -> str:
    return str(unfinished_reviews_count_statement(7).compile(compile_kwargs={"literal_binds": True}))


def test_the_count_query_is_scoped_to_the_user() -> None:
    """Verify one user's reviews never count against another's."""
    assert "requested_by_user_id = 7" in _sql_of_the_count_query()


def test_the_count_query_counts_reviews_that_are_pending() -> None:
    """Verify a review waiting in the queue, or for its repo's index, counts as unfinished."""
    assert "'pending'" in _sql_of_the_count_query()


def test_the_count_query_counts_reviews_that_are_running() -> None:
    """Verify a review being worked on counts as unfinished."""
    assert "'running'" in _sql_of_the_count_query()


def test_the_count_query_does_not_count_finished_reviews() -> None:
    """Verify completed and failed reviews free their slot."""
    sql = _sql_of_the_count_query()

    assert "'completed'" not in sql and "'failed'" not in sql


def _client_for(router, slot_keeper: FakeSlotKeeper) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_review_slot_keeper] = lambda: slot_keeper
    app.dependency_overrides[get_rate_limiter] = lambda: AllowAllRateLimiter()
    return TestClient(app)


@pytest.mark.parametrize(
    "router,path,body",
    [
        (reviews.router, "/api/repos/10/review", {"file_paths": ["a.py"]}),
        (reviews.router, "/api/reviews", {"files": [{"file_path": "a.py", "content": "x = 1\n"}]}),
        (pull_requests.router, "/api/pull-requests/review", {"pr_url": "https://github.com/acme/api/pull/7"}),
    ],
    ids=["repo review", "repoless review", "pull request review"],
)
def test_every_review_submit_route_is_refused_with_429_at_the_limit(router, path: str, body: dict) -> None:
    """Verify no way of starting a review gets around the cap."""
    client = _client_for(router, FakeSlotKeeper(full=True))

    response = client.post(path, json=body)

    assert response.status_code == 429
