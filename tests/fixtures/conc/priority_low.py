"""
    CONC priority=low fixture: unprotected shared state where a lost
    update is cosmetic. _page_view_hits is an approximate, non-critical
    display counter — a concurrent lost increment makes the displayed
    number slightly stale, not corrupted in any way that matters.
"""


class PageViewDisplay:
    def __init__(self) -> None:
        self._page_view_hits = 0

    def record_view(self) -> None:
        self._page_view_hits += 1

    def approximate_views_text(self) -> str:
        return f"~{self._page_view_hits} views"
