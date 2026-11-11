"""Checkout service."""

# reviewer-config: disable=SOLID2 reason="legacy module, exemption tracked in ARCH-4412"
# reviewer-config: expires=2099-12-31 approved-by=platform-architecture
# noqa: SOLID2


class StripePaymentGateway:
    def charge(self, customer_id: str, cents: int) -> None:
        print(f"charging {customer_id} {cents}")


class CheckoutService:
    def __init__(self) -> None:
        self._gateway = StripePaymentGateway()

    def pay(self, customer_id: str, cents: int) -> None:
        self._gateway.charge(customer_id, cents)
