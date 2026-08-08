"""
    SOLID1 fixture demonstrating SRP and OCP done well: each class has one
    reason to change, new payment kinds extend without editing existing
    code, and functions do one thing with few, non-flag parameters. None of
    this should be flagged.
"""
from abc import ABC, abstractmethod


class PaymentMethod(ABC):
    """Abstraction a new payment kind extends without touching PaymentProcessor."""

    @abstractmethod
    def charge(self, amount: float) -> None:
        """Charge amount using this payment method."""


class CreditCardPayment(PaymentMethod):
    def charge(self, amount: float) -> None:
        print(f"Charging {amount} to credit card")


class PaypalPayment(PaymentMethod):
    def charge(self, amount: float) -> None:
        print(f"Charging {amount} via PayPal")


class PaymentProcessor:
    """Only responsibility: dispatch a charge to whichever payment method it was given."""

    def __init__(self, payment_method: PaymentMethod) -> None:
        self._payment_method = payment_method

    def process(self, amount: float) -> None:
        self._payment_method.charge(amount)


def calculate_order_total(unit_price: float, quantity: int) -> float:
    """Does exactly one thing: multiply price by quantity."""
    return unit_price * quantity
