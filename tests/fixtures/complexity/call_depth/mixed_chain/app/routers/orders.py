from app.services.orders import place_order


def create_order(customer_id: int, items: list[str]) -> dict:
    if not items:
        raise ValueError("An order needs at least one item")
    order_id = _submit(customer_id, items)
    return {"order_id": order_id, "status": "created"}


def _submit(customer_id: int, items: list[str]) -> int:
    return _forward(customer_id, items)


def _forward(customer_id: int, items: list[str]) -> int:
    return place_order(customer_id, items)
