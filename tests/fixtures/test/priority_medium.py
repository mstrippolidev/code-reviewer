"""
    TEST priority=medium fixture: real branching logic trapped in a
    static method with no seam. TaxPolicy.rate_for is called directly by
    name and no test can substitute alternate tax behavior without
    changing the class itself.
"""


class TaxPolicy:
    @staticmethod
    def rate_for(region: str, product_category: str, is_business: bool, amount: float) -> float:
        if region == "EU":
            if product_category == "food":
                rate = 0.07
            elif product_category == "digital":
                rate = 0.21
            else:
                rate = 0.19
            if is_business and amount > 1000:
                rate = 0.0
        elif region == "US":
            rate = 0.0 if product_category == "food" else 0.08
        else:
            rate = 0.15
        return rate
