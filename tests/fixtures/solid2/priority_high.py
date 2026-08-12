"""
    SOLID2 priority=high fixture: a DIP violation that blocks testing the
    class in isolation — the concrete repository is constructed inside
    __init__ instead of being injected.
"""


class PostgresOrderRepository:
    def save(self, order_id: str) -> None:
        print(f"INSERT INTO orders VALUES ({order_id})")


class OrderService:
    def __init__(self) -> None:
        self._repository = PostgresOrderRepository()

    def place_order(self, order_id: str) -> None:
        self._repository.save(order_id)
