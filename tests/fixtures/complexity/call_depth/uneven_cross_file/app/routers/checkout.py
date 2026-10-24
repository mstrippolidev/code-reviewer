from app.pricing import price_cart
from app.shipping import ship_cart


def checkout(cart_id: int, items: list[str]) -> dict:
    _validate(items)
    total = price_cart(items)
    tracking = ship_cart(cart_id, items)
    return {"total": total, "tracking": tracking}


def _validate(items: list[str]) -> None:
    if not items:
        raise ValueError("Cart is empty")
