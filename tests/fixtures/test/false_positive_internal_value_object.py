"""
    TEST false-positive fixture: __init__ builds a plain immutable value
    object, not a real collaborator. Should NOT be flagged as a
    hard-coded dependency — there is nothing here a unit test would ever
    need to fake or stub; Point carries no I/O, no clock, no external
    system.
"""


class Point:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class Line:
    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self._start = Point(x1, y1)
        self._end = Point(x2, y2)

    def length(self) -> float:
        return ((self._end.x - self._start.x) ** 2 + (self._end.y - self._start.y) ** 2) ** 0.5
