"""
    CMPLX false-positive trap: price_for makes three calls and every one
    reaches real logic in a single step, so each line costs the reader the
    same. Nothing here is uneven or deep.
"""


def validate_price(price: float) -> None:
    if price < 0:
        raise ValueError("Price must be non-negative")


def flag_for_review(price: float) -> str:
    if price > 10_000:
        return "needs-review"
    return "ok"


def apply_discount(price: float, is_premium: bool) -> float:
    if is_premium:
        return price * 0.9
    return price


def price_for(price: float, is_premium: bool) -> float:
    validate_price(price)
    flag_for_review(price)
    return apply_discount(price, is_premium)
