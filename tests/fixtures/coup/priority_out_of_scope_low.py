"""
    COUP out-of-scope fixture: common coupling through shared global state.
    RequestCounter and RateLimiter never hold a reference to each other,
    but both read and write the same module-level dict, so a change to
    one's write pattern can silently corrupt the other's reads. Not a
    cycle (no reference exists between the two classes), not feature envy
    or intimacy (neither reaches into the other's instance state), not a
    god object, and not a chain through intermediate objects, so it sits
    outside the five in-scope categories.
"""

_request_state: dict[str, int] = {}


class RequestCounter:
    def record(self, client_id: str) -> None:
        _request_state[client_id] = _request_state.get(client_id, 0) + 1


class RateLimiter:
    def __init__(self, max_requests: int) -> None:
        self._max_requests = max_requests

    def is_allowed(self, client_id: str) -> bool:
        return _request_state.get(client_id, 0) < self._max_requests
