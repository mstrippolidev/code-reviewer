"""
    TEST false-positive fixture: a module-level function with real
    branching whose result depends only on its arguments. A test passes
    different arguments to exercise every branch, so it needs no injection
    point and must NOT be flagged as hidden logic.
"""


def shipping_cost(weight_kg: float, express: bool, country: str) -> float:
    if weight_kg <= 0:
        raise ValueError("Weight must be positive")
    base = 5.0 if weight_kg < 2 else 5.0 + (weight_kg - 2) * 1.5
    if country != "US":
        base *= 2
    if express:
        base += 12.0
    return base
