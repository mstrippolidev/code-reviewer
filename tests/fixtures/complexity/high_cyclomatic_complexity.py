def shipping_quote(order: dict) -> float:
    cost = 0.0
    if order["weight"] > 20:
        cost += 15
    elif order["weight"] > 10:
        cost += 8
    else:
        cost += 4
    if order["is_international"]:
        cost += 25
        if order["country"] in ("KP", "IR", "SY"):
            cost += 40
    if order["is_express"]:
        cost *= 1.5
    if order["is_fragile"]:
        cost += 6
    if order["customer_tier"] == "gold":
        cost *= 0.9
    elif order["customer_tier"] == "silver":
        cost *= 0.95
    if order["coupon"] and order["coupon"] == "FREESHIP":
        cost = 0.0
    if cost > 100:
        cost = 100.0
    return cost
