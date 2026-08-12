"""
    COUP violation fixture: feature envy. Every line of
    InvoiceDescriber.describe reads Invoice's data and none of it touches
    the describer's own state, so the method belongs on Invoice.
"""


class Invoice:
    def __init__(self, number: str, subtotal: float, tax_rate: float) -> None:
        self.number = number
        self.subtotal = subtotal
        self.tax_rate = tax_rate
        self.currency = "EUR"


class InvoiceDescriber:
    def __init__(self, locale: str) -> None:
        self._locale = locale

    def describe(self, invoice: Invoice) -> str:
        tax = invoice.subtotal * invoice.tax_rate
        total = invoice.subtotal + tax
        return (
            f"Invoice {invoice.number}: {invoice.subtotal} "
            f"+ {tax} tax = {total} {invoice.currency}"
        )
