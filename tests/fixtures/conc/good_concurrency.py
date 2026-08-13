"""
    CONC fixture demonstrating safe concurrent behavior: shared state is
    always mutated behind a lock, and the async function awaits a
    non-blocking sleep instead of a blocking one. None of this should be
    flagged.
"""
import asyncio
import threading


class SafeCounter:
    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        with self._lock:
            self._count += 1
            return self._count


async def fetch_with_delay(session_id: str, delay_seconds: float) -> str:
    await asyncio.sleep(delay_seconds)
    return f"fetched {session_id}"
