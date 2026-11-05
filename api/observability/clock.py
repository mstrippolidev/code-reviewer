"""
    Elapsed-time helper for the naive UTC timestamps the database stores.
"""
from datetime import UTC, datetime


def seconds_since(naive_utc_timestamp: datetime) -> float:
    """Seconds elapsed since a naive-UTC database timestamp, never negative."""
    return max(0.0, (datetime.now(UTC).replace(tzinfo=None) - naive_utc_timestamp).total_seconds())
