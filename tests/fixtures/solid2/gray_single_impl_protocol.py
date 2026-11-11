"""
    SOLID2 gray-area fixture: a Protocol with exactly one implementation, in
    the same module as its only consumer, with no I/O behind it and no test
    fake. Whether the abstraction earns its place is a judgment call.
"""
from typing import Protocol


class PriceRounder(Protocol):
    def round_price(self, amount: float) -> float: ...


class TwoDecimalRounder:
    def round_price(self, amount: float) -> float:
        return round(amount, 2)


class InvoiceTotals:
    def __init__(self, rounder: PriceRounder) -> None:
        self._rounder = rounder

    def total(self, amounts: list[float]) -> float:
        return self._rounder.round_price(sum(amounts))
