"""
    TCASE priority=medium fixture: a counter whose increment method is
    called concurrently by every incoming request handler, but the paired
    test only exercises it sequentially.
"""


class RequestCounter:
    def __init__(self) -> None:
        self._count = 0

    def increment(self) -> None:
        """Called concurrently by every incoming request handler."""
        self._count += 1

    def total(self) -> int:
        return self._count
