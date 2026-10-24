from app.storage.orders import write_order


def save_order(customer_id: int, items: list[str]) -> int:
    return write_order(customer_id, items)
