"""
    ERR regression fixture: returning None for a legitimately absent value
    is not a failure signal and must not be flagged by item 1.
"""


class UserDirectory:
    def __init__(self, users: dict[str, str]) -> None:
        self._users = users

    def find_by_id(self, user_id: str) -> str | None:
        """Return the user's name, or None when no such user exists."""
        return self._users.get(user_id)
