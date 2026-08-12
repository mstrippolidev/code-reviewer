"""
    COH priority=low fixture: a single trivial, one-line misplaced method —
    is_valid_email never touches the instance's own data, but its impact
    is minimal.
"""


class InvoiceFormatter:
    def __init__(self, currency_symbol: str) -> None:
        self._currency_symbol = currency_symbol

    def format_amount(self, amount: float) -> str:
        return f"{self._currency_symbol}{amount:,.2f}"

    def is_valid_email(self, email: str) -> bool:
        return "@" in email and "." in email.split("@")[-1]
