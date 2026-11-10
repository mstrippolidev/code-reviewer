"""
    VAR out-of-scope fixture: variable shadowing. It's naming-adjacent but
    not one of the four in-scope categories (not an abbreviation, not
    vague, not inconsistent vocabulary, needs no comment to explain it) —
    the prompt's own example of a real finding outside its four
    categories, so it must be flagged, but only at priority low.
"""


discount_rate = 0.10


def apply_discount(price: float, discount_rate: float) -> float:
    return price * (1 - discount_rate)
