"""
    CMPLX hop violation: checkout_total reaches real logic only after 8
    chained same-file hops (nine functions, the entry is not a hop). Even in one file,
    more than 7 chained hops is too many to follow.
"""


def checkout_total(price: float, is_premium: bool) -> float:
    return price_with_rules(price, is_premium)


def price_with_rules(price: float, is_premium: bool) -> float:
    return price_with_region(price, is_premium)


def price_with_region(price: float, is_premium: bool) -> float:
    return price_with_currency(price, is_premium)


def price_with_currency(price: float, is_premium: bool) -> float:
    return price_with_tax(price, is_premium)


def price_with_tax(price: float, is_premium: bool) -> float:
    return price_with_promo(price, is_premium)


def price_with_promo(price: float, is_premium: bool) -> float:
    return price_with_loyalty(price, is_premium)


def price_with_loyalty(price: float, is_premium: bool) -> float:
    return price_with_discount(price, is_premium)


def price_with_discount(price: float, is_premium: bool) -> float:
    return apply_discount(price, is_premium)


def apply_discount(price: float, is_premium: bool) -> float:
    if is_premium:
        return price * 0.9
    return price

