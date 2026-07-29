"""
    Complexity fixture: conditionals nested four levels deep, forcing the
    reader to track every enclosing branch to understand the innermost one.
"""


def resolve_shipping_rate(order: dict) -> float:
    if order["country"] == "US":
        if order["is_express"]:
            if order["weight"] > 50:
                if order["is_fragile"]:
                    return 75.0
                return 60.0
            return 40.0
        return 20.0
    return 50.0
