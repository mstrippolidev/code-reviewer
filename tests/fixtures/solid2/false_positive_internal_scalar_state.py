"""
    SOLID2 false-positive fixture: a private counter is plain internal
    state, not a swappable collaborator. Should NOT be flagged as a DIP
    violation — the prompt itself carves this out: a private scalar,
    counter, or plain data structure is internal state, not a concrete
    dependency.
"""


class RequestThrottle:
    def __init__(self, max_per_window: int) -> None:
        self._max_per_window = max_per_window
        self._count = 0

    def record(self) -> bool:
        self._count += 1
        return self._count <= self._max_per_window
