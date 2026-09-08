"""
    CONC false-positive fixture: shared state mutated only while holding
    a lock. Should NOT be flagged as unprotected shared mutation — item 1
    targets state changed with no lock, queue, atomic primitive, or
    immutability guarding it at all; this mutation is fully guarded.
"""
import threading


class RequestCounter:
    def __init__(self) -> None:
        self._count = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        with self._lock:
            self._count += 1
