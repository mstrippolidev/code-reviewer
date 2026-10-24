from app.repositories.orders import save_order

_BLOCKED_CUSTOMERS = {13, 404}
_MAX_ITEMS = 50


def place_order(customer_id: int, items: list[str]) -> int:
    if customer_id in _BLOCKED_CUSTOMERS:
        raise PermissionError(f"Customer {customer_id} cannot place orders")
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"An order holds at most {_MAX_ITEMS} items")
    return save_order(customer_id, items)
