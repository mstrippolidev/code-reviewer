"""
    TEST gray-area fixture: a function that reads the current time only when
    the caller does not pass one. A test can inject the time through the
    parameter, so the clock is a seam, but the default still hides a call.
"""
from datetime import datetime, timedelta


def is_expired(issued_at: datetime, now: datetime | None = None) -> bool:
    current = now or datetime.utcnow()
    return current - issued_at > timedelta(hours=1)
