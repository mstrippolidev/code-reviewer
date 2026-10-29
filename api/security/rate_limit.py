import time
from collections.abc import Callable

from redis.asyncio import Redis

WINDOW_SECONDS = 60


class RateLimitExceededError(Exception):
    """Raised when a caller has used up their requests for the current minute."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Too many requests. Try again in {retry_after_seconds} seconds.")
        self.retry_after_seconds = retry_after_seconds


class RateLimiter:
    """Counts requests per caller and route group in fixed one-minute windows kept in Redis."""

    def __init__(self, redis: Redis, clock: Callable[[], float] = time.time) -> None:
        self._redis = redis
        self._clock = clock

    async def hit(self, scope: str, subject_id: int, limit: int) -> None:
        """Counts one request by `subject_id` against `scope`'s budget for the current minute.

        Raises RateLimitExceededError, carrying the seconds until the minute ends, once more than
        `limit` requests have been counted. A request that raises is still counted.
        """
        now = self._clock()
        window_number = int(now // WINDOW_SECONDS)
        key = f"rate_limit:{scope}:{subject_id}:{window_number}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, WINDOW_SECONDS)
        if count > limit:
            raise RateLimitExceededError(retry_after_seconds=WINDOW_SECONDS - int(now % WINDOW_SECONDS))
