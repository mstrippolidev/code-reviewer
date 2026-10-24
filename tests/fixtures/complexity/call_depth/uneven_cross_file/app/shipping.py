from app.carriers import book_pickup


def ship_cart(cart_id: int, items: list[str]) -> str:
    return _book(cart_id, items)


def _book(cart_id: int, items: list[str]) -> str:
    return book_pickup(cart_id, items)
