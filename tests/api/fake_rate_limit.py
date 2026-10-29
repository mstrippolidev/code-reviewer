"""
    Stand-ins for the rate limiter: a Redis that only counts, and a limiter for route tests that are
    about something else, which counts nothing and refuses nothing.
"""


class FakeCounterRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds


class AllowAllRateLimiter:
    def __init__(self) -> None:
        self.hits: list[tuple[str, int, int]] = []

    async def hit(self, scope: str, subject_id: int, limit: int) -> None:
        self.hits.append((scope, subject_id, limit))
