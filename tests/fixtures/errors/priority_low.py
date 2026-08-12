"""
    ERR priority=low fixture: an error-code sentinel signaling real
    failure, but confined to a debug-only internal helper nothing else in
    the codebase depends on — a minor case with limited reach.
"""


class _InternalCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def _debug_only_lookup(self, key: str) -> str:
        """Used only by an interactive debug console; never called from
        production paths."""
        if key not in self._store:
            return "ERROR"
        return self._store[key]
