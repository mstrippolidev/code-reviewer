"""
    SOLID2 false-positive trap: a small Protocol that sits beside its
    consumer at an external I/O boundary, with a real implementation and a
    test fake. The abstraction earns its place, so nothing here is flagged.
"""
from typing import Protocol


class PaymentGateway(Protocol):
    def charge(self, customer_id: str, cents: int) -> str: ...


class StripeGateway:
    def charge(self, customer_id: str, cents: int) -> str:
        return f"stripe-charge-{customer_id}-{cents}"


class FakeGateway:
    def charge(self, customer_id: str, cents: int) -> str:
        return "fake-charge"


class InvoiceCharger:
    def __init__(self, gateway: PaymentGateway) -> None:
        self._gateway = gateway

    def charge_invoice(self, customer_id: str, cents: int) -> str:
        if cents <= 0:
            raise ValueError("Invoice amount must be positive")
        return self._gateway.charge(customer_id, cents)
