"""
    BOUND fixture demonstrating healthy boundaries: internal-only state is
    marked private, a mutable collection is only ever handed out as a
    copy, the public surface is exactly what a caller needs, and nothing
    returned is a raw external type. None of this should be flagged.
"""


class OrderBasket:
    """Owns a list of line items; callers can only inspect or mutate
    through methods that keep the basket's own invariants intact."""

    def __init__(self) -> None:
        self._line_items: list[str] = []
        self._discount_applied = False

    def add_item(self, item_name: str) -> None:
        self._line_items.append(item_name)

    def items(self) -> list[str]:
        return list(self._line_items)

    def apply_discount(self) -> None:
        self._discount_applied = True

    @property
    def item_count(self) -> int:
        return len(self._line_items)
