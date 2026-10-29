"""
    Tests for RateLimiter against an in-memory Redis and a controllable clock.
"""
import pytest

from api.security.rate_limit import WINDOW_SECONDS, RateLimiter, RateLimitExceededError
from tests.api.fake_rate_limit import FakeCounterRedis

LIMIT = 3


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def redis() -> FakeCounterRedis:
    return FakeCounterRedis()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(now=WINDOW_SECONDS * 1000 + 10)


@pytest.fixture
def limiter(redis: FakeCounterRedis, clock: FakeClock) -> RateLimiter:
    return RateLimiter(redis, clock)


async def _hit_times(limiter: RateLimiter, times: int, scope: str = "review", subject_id: int = 1) -> None:
    for _ in range(times):
        await limiter.hit(scope, subject_id, LIMIT)


@pytest.mark.asyncio
async def test_requests_up_to_the_limit_are_allowed(limiter: RateLimiter) -> None:
    await _hit_times(limiter, LIMIT)


@pytest.mark.asyncio
async def test_the_request_after_the_limit_is_refused(limiter: RateLimiter) -> None:
    await _hit_times(limiter, LIMIT)

    with pytest.raises(RateLimitExceededError):
        await limiter.hit("review", 1, LIMIT)


@pytest.mark.asyncio
async def test_a_refused_request_tells_how_long_until_the_minute_ends(limiter: RateLimiter) -> None:
    await _hit_times(limiter, LIMIT)

    with pytest.raises(RateLimitExceededError) as refused:
        await limiter.hit("review", 1, LIMIT)

    assert refused.value.retry_after_seconds == WINDOW_SECONDS - 10


@pytest.mark.asyncio
async def test_the_counter_starts_fresh_in_the_next_minute(limiter: RateLimiter, clock: FakeClock) -> None:
    await _hit_times(limiter, LIMIT)
    clock.now += WINDOW_SECONDS

    await limiter.hit("review", 1, LIMIT)


@pytest.mark.asyncio
async def test_another_user_has_their_own_budget(limiter: RateLimiter) -> None:
    await _hit_times(limiter, LIMIT, subject_id=1)

    await limiter.hit("review", 2, LIMIT)


@pytest.mark.asyncio
async def test_another_route_group_has_its_own_budget(limiter: RateLimiter) -> None:
    await _hit_times(limiter, LIMIT, scope="review")

    await limiter.hit("repo_registration", 1, LIMIT)


@pytest.mark.asyncio
async def test_each_counter_expires_with_its_minute(limiter: RateLimiter, redis: FakeCounterRedis) -> None:
    await _hit_times(limiter, 2)

    assert list(redis.expiries.values()) == [WINDOW_SECONDS]
