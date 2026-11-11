"""
    SOLID1 gray-area fixture: a plain value holder whose constructor takes four
    parameters, one past the limit. Every parameter is a simple value and the
    class does one thing, so the count is the only question.
"""
from datetime import date


class ReportWindow:
    def __init__(self, start: date, end: date, timezone: str, label: str) -> None:
        self._start = start
        self._end = end
        self._timezone = timezone
        self._label = label

    def day_count(self) -> int:
        return (self._end - self._start).days + 1

    def title(self) -> str:
        return f"{self._label} ({self._timezone})"
