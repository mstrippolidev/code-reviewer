"""
    ARCH false-positive fixture: business logic building a small
    immutable value object inline as it computes, not an infrastructure
    collaborator. Should NOT be flagged as construction mixed with use —
    a value object carries no behavioral seam a test would ever need to
    substitute; it is just a value, not a dependency.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Money:
    amount: float
    currency: str


class OrderPricer:
    def __init__(self, tax_rate: float) -> None:
        self._tax_rate = tax_rate

    def price_for(self, subtotal: float, currency: str) -> Money:
        total = subtotal + (subtotal * self._tax_rate)
        return Money(total, currency)
