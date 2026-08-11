"""
    COH violation fixture: a method that never touches the instance's own
    data, only a single passed-in argument, suggesting it doesn't actually
    belong to this class.
"""


class InvoiceFormatter:
    def __init__(self, currency_symbol: str) -> None:
        self._currency_symbol = currency_symbol

    def format_amount(self, amount: float) -> str:
        return f"{self._currency_symbol}{amount:,.2f}"

    def is_valid_email(self, email: str) -> bool:
        return "@" in email and "." in email.split("@")[-1]
