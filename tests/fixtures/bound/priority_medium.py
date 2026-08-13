"""
    BOUND priority=medium fixture: SessionStore keeps an internal retry
    counter and a last-cleanup timestamp that exist purely to support its
    own bookkeeping, but neither is marked private, so nothing signals a
    reader that they are not part of the class's actual contract.
"""
import time


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}
        self.retry_count = 0
        self.last_cleanup_at = time.time()

    def create(self, session_id: str, user_id: str) -> None:
        self.sessions[session_id] = user_id

    def get(self, session_id: str) -> str | None:
        return self.sessions.get(session_id)
