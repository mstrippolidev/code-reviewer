"""
    CONC priority=high fixture: shared mutable state mutated from
    multiple concurrent async tasks with no protection at all.
    SessionStore.sessions is a plain dict written by every handle_login
    call with no lock, so concurrent logins can lose or corrupt entries.
"""


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, str] = {}

    async def handle_login(self, user_id: str, token: str) -> None:
        existing = self.sessions.get(user_id, "")
        self.sessions[user_id] = existing + token
