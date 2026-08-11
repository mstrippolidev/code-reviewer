"""
    COH fixture demonstrating good cohesion: every method reads or writes
    the same instance state and serves the same purpose. None of this
    should be flagged.
"""


class ShoppingCart:
    """Tracks the items and running total for a single checkout session."""

    def __init__(self) -> None:
        self._items: list[tuple[str, float]] = []
        self._total = 0.0

    def add_item(self, name: str, price: float) -> None:
        self._items.append((name, price))
        self._total += price

    def remove_item(self, name: str) -> None:
        for item in self._items:
            if item[0] == name:
                self._items.remove(item)
                self._total -= item[1]
                break

    def item_count(self) -> int:
        return len(self._items)

    def total(self) -> float:
        return self._total
