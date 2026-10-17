"""
    CMPLX medium fixture: checkout_total reaches real logic after 6
    chained same-file hops (seven functions, the entry is not a hop).
    Same-file helpers are cheap to read, so 5 hops would be fine, but 6 or
    7 starts to cost the reader, which is medium.
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
    return apply_discount(price, is_premium)


def apply_discount(price: float, is_premium: bool) -> float:
    if is_premium:
        return price * 0.9
    return price

