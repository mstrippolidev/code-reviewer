"""
    Complexity fixture: six exit points scattered across a guard, a loop,
    and a trailing check, making it hard to know what state the function
    leaves things in without tracing every branch.
"""


def validate_and_process_order(order: dict) -> str:
    if not order:
        return "invalid: empty order"
    if order.get("total", 0) <= 0:
        return "invalid: non-positive total"

    for item in order.get("items", []):
        if item.get("quantity", 0) <= 0:
            return "invalid: item quantity"
        if item.get("price", 0) < 0:
            return "invalid: item price"

    if order.get("status") == "cancelled":
        return "skipped: order cancelled"
    return "processed"
