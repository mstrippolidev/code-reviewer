"""
    SOLID1 priority=high fixture: an OCP violation on a path that changes
    often — every new customer tier requires editing this function instead
    of extending it.
"""


def calculate_discount(customer_type: str, amount: float) -> float:
    if customer_type == "regular":
        return amount * 0.95
    elif customer_type == "premium":
        return amount * 0.9
    elif customer_type == "vip":
        return amount * 0.8
    elif customer_type == "employee":
        return amount * 0.5
    else:
        return amount
