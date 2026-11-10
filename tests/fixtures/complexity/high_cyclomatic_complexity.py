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
    if order["is_express"]:
        cost *= 1.5
    if order["is_fragile"]:
        cost += 6
    if order["is_oversized"]:
        cost += 12
    if order["requires_signature"]:
        cost += 3
    if order["is_insured"]:
        cost += 5
    if order["is_hazardous"]:
        cost += 30
    if order["is_refrigerated"]:
        cost += 18
    if order["is_gift"]:
        cost += 2
    if order["customer_tier"] == "gold":
        cost *= 0.9
    elif order["customer_tier"] == "silver":
        cost *= 0.95
    elif order["customer_tier"] == "bronze":
        cost *= 0.98
    if order["coupon"] == "FREESHIP":
        cost = 0.0
    if cost > 100:
        cost = 100.0
    return cost
