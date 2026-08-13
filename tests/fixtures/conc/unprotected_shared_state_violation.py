"""
    CONC violation fixture: unprotected shared mutable state. RequestStats
    is shared across worker threads and increment() mutates
    self._total_requests with no lock at all, so concurrent calls can lose
    increments.
"""
import threading


class RequestStats:
    def __init__(self) -> None:
        self._total_requests = 0

    def increment(self) -> None:
        self._total_requests += 1

    def total(self) -> int:
        return self._total_requests


def run_workers(stats: RequestStats, request_count: int) -> None:
    threads = [threading.Thread(target=stats.increment) for _ in range(request_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
