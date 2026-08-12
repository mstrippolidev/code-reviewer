"""
    VAR out-of-scope fixture: variable shadowing. It's naming-adjacent but
    not one of the four in-scope categories (not an abbreviation, not
    vague, not inconsistent vocabulary, needs no comment to explain it) —
    the prompt's own example of a real finding outside its four
    categories, so it must be flagged, but only at priority low.
"""


class DiscountCalculator:
    def __init__(self, discount_percentage: float) -> None:
        self.discount_percentage = discount_percentage

    def apply(self, discount_percentage: float) -> float:
        return discount_percentage * (1 - self.discount_percentage)
