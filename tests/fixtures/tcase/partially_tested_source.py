"""
    TCASE fixture: a function whose paired test file covers the empty-list
    and single-item cases but leaves the negative-value and rounding paths
    unasserted.
"""


def calculate_total(amounts: list[float]) -> float:
    if not amounts:
        return 0.0
    total = 0.0
    for amount in amounts:
        if amount < 0:
            raise ValueError("Amounts must be non-negative")
        total += amount
    return round(total, 2)
