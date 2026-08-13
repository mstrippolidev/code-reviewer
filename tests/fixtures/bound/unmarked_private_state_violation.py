"""
    BOUND unmarked-private-state fixture: PriceCalculator carries a cache
    dict and a computation counter that exist purely to support its own
    internal working, but neither is marked private, so nothing signals
    to a reader or caller that they are not part of the class's actual
    offering.
"""


class PriceCalculator:
    def __init__(self, tax_rate: float) -> None:
        self.tax_rate = tax_rate
        self.cache: dict[float, float] = {}
        self.computation_count = 0

    def price_for(self, subtotal: float) -> float:
        if subtotal in self.cache:
            return self.cache[subtotal]
        self.computation_count += 1
        total = subtotal + (subtotal * self.tax_rate)
        self.cache[subtotal] = total
        return total
