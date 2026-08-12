"""
    TCASE priority=high fixture: a shipping-cost calculator called by
    every order in the system, with three pricing tiers and a validation
    branch — the paired test only exercises the first tier.
"""


def calculate_shipping_cost(weight_kg: float) -> float:
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    if weight_kg <= 1:
        return 5.0
    if weight_kg <= 5:
        return 5.0 + (weight_kg - 1) * 2.0
    return 5.0 + 4 * 2.0 + (weight_kg - 5) * 1.5
