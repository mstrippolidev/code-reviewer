"""
    TEST priority=medium fixture: real branching logic trapped in a
    static method with no seam. DiscountPolicy.rate_for is called
    directly by name and no test can substitute alternate discount
    behavior without changing the class itself.
"""


class DiscountPolicy:
    @staticmethod
    def rate_for(customer_tier: str, order_total: float) -> float:
        if customer_tier == "gold":
            return 0.2 if order_total > 100 else 0.1
        if customer_tier == "silver":
            return 0.1 if order_total > 100 else 0.05
        return 0.0
