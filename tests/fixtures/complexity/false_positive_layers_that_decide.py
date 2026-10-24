"""
    CMPLX false-positive trap: three layers, and each one decides
    something: the route validates, the service authorizes, the repository
    hides the I/O. Three hops with real logic at every one is acceptable.
"""
from typing import Protocol


class OrderStore(Protocol):
    def load(self, order_id: str) -> dict[str, str]: ...


class OrderService:
    def __init__(self, store: OrderStore) -> None:
        self._store = store

    def order_for(self, order_id: str, user_id: str) -> dict[str, str]:
        order = self._store.load(order_id)
        if order["owner_id"] != user_id:
            raise PermissionError("Order belongs to another user")
        return order


def get_order(service: OrderService, order_id: str, user_id: str) -> dict[str, str]:
    if not order_id:
        raise ValueError("order_id is required")
    return service.order_for(order_id, user_id)
