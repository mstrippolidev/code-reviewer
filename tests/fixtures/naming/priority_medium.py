"""
    VAR priority=medium fixture: a private helper with a vague, generic
    name. It slows understanding, but its scope is narrow — used only
    inside this one class.
"""


class InvoiceRenderer:
    def __init__(self, currency_symbol: str) -> None:
        self._currency_symbol = currency_symbol

    def render(self, amount: float) -> str:
        return self._handle(amount)

    def _handle(self, amount: float) -> str:
        return f"{self._currency_symbol}{amount:,.2f}"
