"""
    CMPLX gray-area fixture: a flat ladder of four returns at depth one. They
    are not preconditions, so they are not guard clauses, but nothing is nested
    and each return is predictable from the line above it.
"""


def shipping_tier(weight_kg: float) -> str:
    if weight_kg < 1:
        return "envelope"
    if weight_kg < 5:
        return "small"
    if weight_kg < 20:
        return "medium"
    return "freight"
