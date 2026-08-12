"""
    CMPLX regression fixture: four flat, top-level guard clauses (no
    nesting) are the preferred flatter alternative to nested conditionals
    and must not be flagged for exceeding 3 exit points.
"""


def apply_discount(order_total: float, is_member: bool, coupon: str) -> float:
    if order_total <= 0:
        return 0.0
    if coupon == "HALF":
        return order_total * 0.5
    if is_member:
        return order_total * 0.9
    return order_total
