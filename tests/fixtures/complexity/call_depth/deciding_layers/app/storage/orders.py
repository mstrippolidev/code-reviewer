_ORDERS: dict[int, tuple[int, list[str]]] = {}


def write_order(customer_id: int, items: list[str]) -> int:
    order_id = len(_ORDERS) + 1
    _ORDERS[order_id] = (customer_id, items)
    return order_id
