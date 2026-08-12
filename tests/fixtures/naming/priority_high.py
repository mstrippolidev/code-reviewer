"""
    VAR priority=high fixture: a public, widely-used method name that
    strongly implies read-only persistence but silently deletes stale
    records as a side effect — misreading it risks a real bug for any
    caller.
"""


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def save(self, session_id: str, payload: dict) -> None:
        """Public entry point every caller in the codebase uses to persist
        a session."""
        self._sessions[session_id] = payload
        self._purge_expired_sessions()

    def _purge_expired_sessions(self) -> None:
        for stale_id in [sid for sid, data in self._sessions.items() if data.get("expired")]:
            del self._sessions[stale_id]
