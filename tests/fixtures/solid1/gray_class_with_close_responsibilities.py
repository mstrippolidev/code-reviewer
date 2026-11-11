"""
    SOLID1 gray-area fixture: an invoice that holds its line items, totals them
    and also renders a one-line text summary. Rendering and totalling are close
    enough that splitting them is debatable.
"""


class Invoice:
    def __init__(self, customer: str) -> None:
        self._customer = customer
        self._amounts: list[float] = []

    def add_line(self, amount: float) -> None:
        self._amounts.append(amount)

    def total(self) -> float:
        return round(sum(self._amounts), 2)

    def summary(self) -> str:
        return f"{self._customer}: {len(self._amounts)} lines, total {self.total():.2f}"
