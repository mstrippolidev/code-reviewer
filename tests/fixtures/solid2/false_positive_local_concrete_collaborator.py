"""
    SOLID2 false-positive trap: a same-module collaborator with one
    implementation, no I/O, and no need for a substitute. Depending on it
    directly is correct; an interface here would only add a layer.
"""


class DiscountPolicy:
    def apply(self, price: float, is_premium: bool) -> float:
        if is_premium:
            return price * 0.9
        return price


class CheckoutTotal:
    def __init__(self) -> None:
        self._policy = DiscountPolicy()

    def total(self, price: float, is_premium: bool) -> float:
        return self._policy.apply(price, is_premium)
