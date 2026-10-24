from app.storage.orders import write_order


def submit_order(customer_id: int, items: list[str]) -> int:
    return write_order(customer_id, items)
