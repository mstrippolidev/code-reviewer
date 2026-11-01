"""
    A stand-in for ReviewSlotKeeper in tests that are about something else: it records which users were checked and
    which reserved a slot. Built `full` it refuses both; built `refusing_reservation_only` the early check passes and
    only the reservation refuses, which is what a request that lost a race for the last slot sees.
"""
from api.review.errors import TooManyUnfinishedReviewsError


class FakeSlotKeeper:
    def __init__(self, *, full: bool = False, refusing_reservation_only: bool = False, limit: int = 3) -> None:
        self._full = full
        self._refusing_reservation_only = refusing_reservation_only
        self._limit = limit
        self.checked: list[int] = []
        self.reserved: list[int] = []

    async def ensure_capacity(self, user_id: int) -> None:
        self.checked.append(user_id)
        if self._full:
            raise TooManyUnfinishedReviewsError(self._limit)

    async def reserve(self, user_id: int) -> None:
        self.reserved.append(user_id)
        if self._full or self._refusing_reservation_only:
            raise TooManyUnfinishedReviewsError(self._limit)
