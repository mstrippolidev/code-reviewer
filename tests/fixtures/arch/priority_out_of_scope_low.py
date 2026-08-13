"""
    ARCH out-of-scope fixture: the same business rule implemented twice
    in two different layers at once. The minimum-order-amount check is
    enforced both in the request handler (OrderEndpoint) and again inside
    the domain object (Order), so the rule has two homes that can quietly
    drift apart. Not a layering violation (neither reaches for
    infrastructure it should not), not a wrong-direction dependency, not
    construction mixed with use, and not a shape mismatch between
    siblings, so it sits outside the four in-scope categories.
"""

MINIMUM_ORDER_AMOUNT = 10.0


class Order:
    def __init__(self, amount: float) -> None:
        if amount < MINIMUM_ORDER_AMOUNT:
            raise ValueError("order amount below minimum")
        self.amount = amount


class OrderEndpoint:
    def handle(self, amount: float) -> Order:
        if amount < MINIMUM_ORDER_AMOUNT:
            raise ValueError("order amount below minimum")
        return Order(amount)
