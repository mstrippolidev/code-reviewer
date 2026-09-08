"""
    SOLID1 false-positive fixture: adding a new discount strategy through a
    new class implementing an existing Protocol. Should NOT be flagged as
    an OCP violation — new behavior arrives as a new class, and nothing in
    the existing DiscountEngine or its earlier strategies is edited.
"""
from typing import Protocol


class DiscountStrategy(Protocol):
    def discount_for(self, subtotal: float) -> float: ...


class NoDiscount:
    def discount_for(self, subtotal: float) -> float:
        return 0.0


class LoyaltyDiscount:
    def discount_for(self, subtotal: float) -> float:
        return subtotal * 0.1


class SeasonalDiscount:
    def discount_for(self, subtotal: float) -> float:
        return subtotal * 0.15


class DiscountEngine:
    def __init__(self, strategy: DiscountStrategy) -> None:
        self._strategy = strategy

    def final_price(self, subtotal: float) -> float:
        return subtotal - self._strategy.discount_for(subtotal)
