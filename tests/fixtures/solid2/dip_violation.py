"""
    DIP violation fixture: a class constructs its own concrete dependency
    internally instead of receiving it through the constructor, making it
    impossible to substitute or test in isolation.
"""


class PostgresOrderRepository:
    def save(self, order_id: str) -> None:
        print(f"INSERT INTO orders VALUES ({order_id})")


class OrderService:
    def __init__(self) -> None:
        self._repository = PostgresOrderRepository()

    def place_order(self, order_id: str) -> None:
        self._repository.save(order_id)
