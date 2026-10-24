from app.services.orders import place_order


def create_order(customer_id: int, items: list[str]) -> dict:
    if not items:
        raise ValueError("An order needs at least one item")
    order_id = place_order(customer_id, items)
    return {"order_id": order_id, "status": "created"}
