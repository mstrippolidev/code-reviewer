def book_pickup(cart_id: int, items: list[str]) -> str:
    return _reserve(cart_id, items)


def _reserve(cart_id: int, items: list[str]) -> str:
    if len(items) > 20:
        return f"freight-{cart_id}"
    return f"parcel-{cart_id}"
