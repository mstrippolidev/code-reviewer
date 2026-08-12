"""
    VAR priority=low fixture: inconsistent vocabulary for the same concept,
    but confined to one small, low-traffic internal helper — a minor
    inconsistency with limited reach.
"""


class ReportCache:
    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def get_report(self, report_id: str) -> str | None:
        return self._cache.get(report_id)

    def _fetch_report_from_cache(self, report_id: str) -> str | None:
        return self._cache.get(report_id)
