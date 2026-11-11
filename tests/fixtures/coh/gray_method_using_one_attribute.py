"""
    COH gray-area fixture: a profile class whose methods mostly share state,
    plus one method that touches only a single unrelated attribute. It may be a
    small cohesion gap or an ordinary accessor.
"""


class UserProfile:
    def __init__(self, first_name: str, last_name: str, avatar_id: str) -> None:
        self._first_name = first_name
        self._last_name = last_name
        self._avatar_id = avatar_id

    def full_name(self) -> str:
        return f"{self._first_name} {self._last_name}"

    def initials(self) -> str:
        return f"{self._first_name[0]}{self._last_name[0]}"

    def avatar_url(self) -> str:
        return f"https://cdn.example.com/avatars/{self._avatar_id}.png"
