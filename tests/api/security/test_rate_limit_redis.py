"""
    RateLimiter against the real local Redis. Uses a scope no real route uses and deletes its own keys.
"""
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from api.config.settings import get_api_settings
from api.security.rate_limit import WINDOW_SECONDS, RateLimiter, RateLimitExceededError

pytestmark = [pytest.mark.redis, pytest.mark.asyncio]

SCOPE = "rate_limit_integration_test"
SUBJECT_ID = 980_000_001
LIMIT = 2


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_api_settings().redis_url)
    yield client
    keys = [key async for key in client.scan_iter(match=f"rate_limit:{SCOPE}:*")]
    if keys:
        await client.delete(*keys)
    await client.aclose()


async def test_the_request_over_the_limit_is_refused_by_the_real_counter(redis: Redis) -> None:
    limiter = RateLimiter(redis)

    await limiter.hit(SCOPE, SUBJECT_ID, LIMIT)
    await limiter.hit(SCOPE, SUBJECT_ID, LIMIT)

    with pytest.raises(RateLimitExceededError):
        await limiter.hit(SCOPE, SUBJECT_ID, LIMIT)


async def test_the_counter_key_expires_within_the_window(redis: Redis) -> None:
    await RateLimiter(redis).hit(SCOPE, SUBJECT_ID, LIMIT)

    [key] = [key async for key in redis.scan_iter(match=f"rate_limit:{SCOPE}:*")]
    assert 0 < await redis.ttl(key) <= WINDOW_SECONDS
