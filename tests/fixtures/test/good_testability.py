"""
    TEST fixture demonstrating good testability: every collaborator is
    injected through the constructor, no global state is touched, and the
    one static method is a pure, trivial calculation. None of this should
    be flagged.
"""


class TaxCalculator:
    def flat_rate(self, subtotal: float, rate: float) -> float:
        return subtotal * rate


class InvoiceService:
    """Computes an invoice total using an injected tax calculator."""

    def __init__(self, tax_calculator: TaxCalculator) -> None:
        self._tax_calculator = tax_calculator

    def total(self, subtotal: float, tax_rate: float) -> float:
        tax = self._tax_calculator.flat_rate(subtotal, tax_rate)
        return subtotal + tax
