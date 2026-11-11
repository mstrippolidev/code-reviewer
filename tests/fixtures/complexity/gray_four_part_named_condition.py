"""
    CMPLX gray-area fixture: a four-part condition, one past the limit, but the
    parts are first given names so the final test reads as a sentence.
"""


def can_checkout(cart_total: float, user: dict, stock_ok: bool) -> bool:
    is_verified = user.get("verified", False)
    has_address = bool(user.get("address"))
    within_limit = cart_total <= user.get("credit_limit", 0)
    return is_verified and has_address and within_limit and stock_ok
