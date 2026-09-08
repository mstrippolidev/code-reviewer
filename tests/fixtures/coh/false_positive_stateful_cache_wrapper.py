"""
    COH false-positive fixture: get/set/evict look like three different
    jobs, but every method reads or writes the same instance dict. Should
    NOT be flagged as disjoint methods — there is only one cluster of
    state, touched by all three.
"""


class TtlCache:
    def __init__(self) -> None:
        self._entries: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self._entries.get(key)

    def set(self, key: str, value: object) -> None:
        self._entries[key] = value

    def evict(self, key: str) -> None:
        self._entries.pop(key, None)
