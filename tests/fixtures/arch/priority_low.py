"""
    ARCH priority=low fixture: a single environment variable read inside
    otherwise clean domain logic. DiscountRule is almost entirely a pure
    business rule, but one branch reaches for an environment flag rather
    than receiving it as a parameter — a minor, narrow lapse rather than
    the class being generally coupled to infrastructure.
"""
import os


class DiscountRule:
    def __init__(self, percentage: float) -> None:
        self._percentage = percentage

    def apply(self, price: float) -> float:
        discounted = price * (1 - self._percentage)
        if os.environ.get("DISCOUNT_DEBUG"):
            print(f"applied {self._percentage} to {price} -> {discounted}")
        return discounted
