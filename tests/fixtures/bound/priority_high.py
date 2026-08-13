"""
    BOUND priority=high fixture: InventoryLevel hands out its own mutable
    stock dict directly, with no defensive copy, so external code can
    rewrite quantities for any SKU without going through reserve() or
    release(), which are the only methods meant to keep stock consistent.
"""


class InventoryLevel:
    def __init__(self) -> None:
        self.stock_by_sku: dict[str, int] = {}

    def reserve(self, sku: str, quantity: int) -> None:
        available = self.stock_by_sku.get(sku, 0)
        if quantity > available:
            raise ValueError("insufficient stock")
        self.stock_by_sku[sku] = available - quantity

    def release(self, sku: str, quantity: int) -> None:
        self.stock_by_sku[sku] = self.stock_by_sku.get(sku, 0) + quantity

    def snapshot(self) -> dict[str, int]:
        return self.stock_by_sku
