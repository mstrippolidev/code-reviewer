from app.gateways.orders import submit_order


def place_order(customer_id: int, items: list[str]) -> int:
    return submit_order(customer_id, items)
