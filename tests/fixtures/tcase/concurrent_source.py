"""
    TCASE fixture: a counter mutated across calls, documented as used from
    concurrent contexts but tested only sequentially.
"""


class RequestCounter:
    """Tracks in-flight requests; increment is called concurrently from
    multiple async request handlers."""

    def __init__(self) -> None:
        self._count = 0

    def increment(self) -> None:
        self._count += 1

    def current_count(self) -> int:
        return self._count
