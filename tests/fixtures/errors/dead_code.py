"""
    Error handling fixture: unreachable code left after an unconditional
    return, which can never run and misleads a reader about the function's
    behavior.
"""


def calculate_shipping_cost(weight: float) -> float:
    if weight <= 0:
        raise ValueError("Weight must be positive")
    return weight * 2.5
    print("Shipping cost calculated")
