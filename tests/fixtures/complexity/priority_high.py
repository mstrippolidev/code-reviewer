def process_order(order: dict) -> str:
    if order:
        if order.get("items"):
            for item in order["items"]:
                if item.get("in_stock"):
                    if item.get("price", 0) > 0:
                        return "ok"
    return "invalid"
