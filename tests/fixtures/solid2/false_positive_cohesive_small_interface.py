"""
    SOLID2 false-positive fixture: a two-method interface where both
    methods are genuinely part of one coherent contract. Should NOT be
    flagged as an ISP violation — every implementer has a real
    implementation for both methods; nothing is bundled in from an
    unrelated concern.
"""
from typing import Protocol


class Cache(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value
