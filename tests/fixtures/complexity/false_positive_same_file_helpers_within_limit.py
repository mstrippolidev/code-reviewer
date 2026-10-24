"""
    CMPLX false-positive trap: checkout_total reaches real logic after 5
    chained same-file hops (six functions, the entry is not a hop).
    Same-file helpers are easy to read, so up to 5 hops is acceptable.
"""


def checkout_total(price: float, is_premium: bool) -> float:
    return price_with_rules(price, is_premium)


def price_with_rules(price: float, is_premium: bool) -> float:
    return price_with_region(price, is_premium)


def price_with_region(price: float, is_premium: bool) -> float:
    return price_with_tax(price, is_premium)


def price_with_tax(price: float, is_premium: bool) -> float:
    return price_with_promo(price, is_premium)


def price_with_promo(price: float, is_premium: bool) -> float:
    return apply_discount(price, is_premium)


def apply_discount(price: float, is_premium: bool) -> float:
    if is_premium:
        return price * 0.9
    return price

