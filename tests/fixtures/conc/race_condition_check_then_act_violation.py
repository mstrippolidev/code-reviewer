"""
    CONC violation fixture: a check-then-act race. get_or_compute checks
    whether a key is cached and, if not, computes and stores it — but the
    check and the write are two separate steps with no lock, so two
    concurrent callers can both see the key missing and both compute and
    overwrite it.
"""


class ExpensiveResultCache:
    def __init__(self) -> None:
        self._cache: dict[str, int] = {}

    def get_or_compute(self, key: str) -> int:
        if key not in self._cache:
            self._cache[key] = self._expensive_computation(key)
        return self._cache[key]

    def _expensive_computation(self, key: str) -> int:
        return sum(ord(character) for character in key)
