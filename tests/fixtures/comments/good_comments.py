"""
    Comment fixture: comments that ARE justified — a WHY comment for a
    non-obvious quirk, a consumer-facing docstring, and a function with no
    comment at all. None of this should be flagged.
"""


def parse_timestamp(raw: str) -> int:
    # The upstream API sends timestamps in milliseconds, not seconds.
    return int(raw) // 1000


class RetryPolicy:
    """Determines how many times an operation should be retried before giving up."""

    def __init__(self, max_attempts: int = 3) -> None:
        self._max_attempts = max_attempts

    def should_retry(self, attempt_number: int) -> bool:
        return attempt_number < self._max_attempts
