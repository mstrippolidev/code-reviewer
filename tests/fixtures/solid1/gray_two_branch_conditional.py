"""
    SOLID1 gray-area fixture: a conditional with only two branches that picks a
    shipping rate. A third case would mean editing it, but two cases do not
    clearly call for an extension point yet.
"""


def shipping_cost(weight_kg: float, express: bool) -> float:
    if express:
        return 15.0 + weight_kg * 2.0
    return 5.0 + weight_kg * 0.5
