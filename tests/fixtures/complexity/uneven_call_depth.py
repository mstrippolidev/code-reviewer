"""
    CMPLX uneven-depth fixture: price_for makes three calls. The first two
    are helpers that decide something in one step; the third goes through
    a chain of forwarding layers before it reaches real logic. Total hops
    stay inside the same-file limit, so only the odd-one-out depth is the
    problem, which is medium.
"""


def validate_price(price: float) -> None:
    if price < 0:
        raise ValueError("Price must be non-negative")


def record_price_check(price: float) -> str:
    if price > 10_000:
        return "needs-review"
    return "ok"


def price_for(price: float, is_premium: bool) -> float:
    validate_price(price)
    record_price_check(price)
    return discount_entry(price, is_premium)


def discount_entry(price: float, is_premium: bool) -> float:
    return discount_router(price, is_premium)


def discount_router(price: float, is_premium: bool) -> float:
    return discount_dispatch(price, is_premium)


def discount_dispatch(price: float, is_premium: bool) -> float:
    return apply_discount(price, is_premium)


def apply_discount(price: float, is_premium: bool) -> float:
    if is_premium:
        return price * 0.9
    return price
