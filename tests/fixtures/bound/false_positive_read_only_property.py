"""
    BOUND false-positive fixture: Temperature exposes its value only
    through a read-only property, with no setter and no way for external
    code to assign a new value directly. Should NOT be flagged as leaking
    internal representation — the value is a plain immutable float, and
    exposing it read-only is not the same as handing out a mutable
    collection external code can corrupt.
"""


class Temperature:
    def __init__(self, celsius: float) -> None:
        self._celsius = celsius

    @property
    def celsius(self) -> float:
        return self._celsius

    @property
    def fahrenheit(self) -> float:
        return (self._celsius * 9 / 5) + 32
