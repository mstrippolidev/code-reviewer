"""
    SOLID1 false-positive fixture: a fluent builder with many small setter
    methods. Should NOT be flagged as an SRP violation — every method
    exists for the same single reason to change (the shape of the
    RequestConfig it assembles), not several unrelated responsibilities.
"""


class RequestConfigBuilder:
    def __init__(self) -> None:
        self._headers: dict[str, str] = {}
        self._timeout_seconds: float = 30.0
        self._retries: int = 0

    def with_header(self, name: str, value: str) -> "RequestConfigBuilder":
        self._headers[name] = value
        return self

    def with_timeout(self, timeout_seconds: float) -> "RequestConfigBuilder":
        self._timeout_seconds = timeout_seconds
        return self

    def with_retries(self, retries: int) -> "RequestConfigBuilder":
        self._retries = retries
        return self

    def build(self) -> dict[str, object]:
        return {
            "headers": self._headers,
            "timeout_seconds": self._timeout_seconds,
            "retries": self._retries,
        }
