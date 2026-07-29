"""
    Example of clean, well-named code. Shared "should not be flagged" fixture,
    reusable across multiple agents' test suites, not just naming.
"""


def filter_active_subscribers(subscribers: list[dict]) -> list[dict]:
    """Return only subscribers whose subscription is currently active."""
    return [subscriber for subscriber in subscribers if subscriber["is_active"]]


class InvoiceNumberGenerator:
    """Generates unique, sequential invoice numbers for a billing account."""

    def __init__(self, starting_number: int = 1000) -> None:
        self._next_invoice_number = starting_number

    def generate_next_invoice_number(self) -> int:
        invoice_number = self._next_invoice_number
        self._next_invoice_number += 1
        return invoice_number
