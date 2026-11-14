from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    sku: str
    unit_price_cents: int
    quantity: int

    def total_cents(self) -> int:
        return self.unit_price_cents * self.quantity


class Basket:
    """Holds the line items of one checkout and everything derived from them."""

    def __init__(self) -> None:
        self._items: dict[str, LineItem] = {}

    def add(self, item: LineItem) -> None:
        existing = self._items.get(item.sku)
        if existing is None:
            self._items[item.sku] = item
            return
        self._items[item.sku] = LineItem(
            item.sku, existing.unit_price_cents, existing.quantity + item.quantity
        )

    def remove(self, sku: str) -> None:
        self._items.pop(sku, None)

    def item_count(self) -> int:
        return sum(item.quantity for item in self._items.values())

    def subtotal_cents(self) -> int:
        return sum(item.total_cents() for item in self._items.values())

    def is_empty(self) -> bool:
        return not self._items
