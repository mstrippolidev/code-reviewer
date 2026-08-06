"""
    SOLID2 fixture demonstrating LSP, ISP, and DIP done well: an injected
    abstraction, a cohesive interface, and subclasses that fully honor
    their parent's contract. None of this should be flagged.
"""
from abc import ABC, abstractmethod


class OrderRepository(ABC):
    """Abstraction for persisting an order, with exactly one responsibility."""

    @abstractmethod
    def save(self, order_id: str) -> None:
        """Persist order_id."""


class PostgresOrderRepository(OrderRepository):
    def save(self, order_id: str) -> None:
        print(f"INSERT INTO orders VALUES ({order_id})")


class InMemoryOrderRepository(OrderRepository):
    def __init__(self) -> None:
        self._saved_order_ids: list[str] = []

    def save(self, order_id: str) -> None:
        self._saved_order_ids.append(order_id)


class OrderService:
    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def place_order(self, order_id: str) -> None:
        self._repository.save(order_id)
