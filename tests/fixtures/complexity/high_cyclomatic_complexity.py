"""
    Complexity fixture: seven branches combining multiple independent
    conditions per branch, not a simple one-to-one lookup, driving up the
    number of paths through the function.
"""


def calculate_order_priority(order: dict) -> str:
    if order["is_vip"] and order["total"] > 1000:
        return "urgent"
    elif order["is_vip"]:
        return "high"
    elif order["total"] > 500 and order["items_count"] > 10:
        return "high"
    elif order["total"] > 500:
        return "medium"
    elif order["is_international"] and order["items_count"] > 5:
        return "medium"
    elif order["is_international"]:
        return "low"
    else:
        return "standard"
