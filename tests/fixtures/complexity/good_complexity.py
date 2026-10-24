def apply_discount(price: float, is_premium: bool) -> float:
    if price < 0:
        raise ValueError("Price must be non-negative")

    if is_premium:
        return price * 0.9
    return price
