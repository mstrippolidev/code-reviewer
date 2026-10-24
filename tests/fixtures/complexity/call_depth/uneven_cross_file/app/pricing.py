def price_cart(items: list[str]) -> float:
    if len(items) > 10:
        return len(items) * 9.0
    return len(items) * 10.0
