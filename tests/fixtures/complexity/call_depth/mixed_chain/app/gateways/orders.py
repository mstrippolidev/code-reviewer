from app.repositories.orders import save_order


def submit_order(customer_id: int, items: list[str]) -> int:
    return save_order(customer_id, items)
