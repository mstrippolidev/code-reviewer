"""
    BOUND false-positive fixture: Shape marks _area_cache with a leading
    underscore and only its own subclasses touch it, exactly the
    protected-for-subclasses pattern the underscore convention exists to
    signal. Should NOT be flagged as unmarked internal state — it is
    marked, and used only within the class hierarchy it belongs to.
"""


class Shape:
    def __init__(self) -> None:
        self._area_cache: float | None = None

    def area(self) -> float:
        if self._area_cache is None:
            self._area_cache = self._compute_area()
        return self._area_cache

    def _compute_area(self) -> float:
        raise NotImplementedError


class Square(Shape):
    def __init__(self, side: float) -> None:
        super().__init__()
        self._side = side

    def _compute_area(self) -> float:
        return self._side * self._side
