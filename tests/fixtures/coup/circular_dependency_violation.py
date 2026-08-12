"""
    COUP violation fixture: a visible cycle. Order holds a Customer and
    calls into it, and Customer holds the same Order back and calls into
    it, so neither class can be read, changed, or tested alone.
"""


class Order:
    def __init__(self, order_id: str) -> None:
        self._order_id = order_id
        self._customer: "Customer | None" = None
        self._lines: list[float] = []

    def attach_customer(self, customer: "Customer") -> None:
        self._customer = customer
        customer.attach_order(self)

    def add_line(self, amount: float) -> None:
        self._lines.append(amount)

    def total(self) -> float:
        return sum(self._lines)

    def discounted_total(self) -> float:
        return self.total() - self._customer.loyalty_discount()


class Customer:
    def __init__(self, name: str) -> None:
        self._name = name
        self._order: Order | None = None

    def attach_order(self, order: Order) -> None:
        self._order = order

    def loyalty_discount(self) -> float:
        return 5.0

    def summary(self) -> str:
        return f"{self._name} owes {self._order.total()}"
