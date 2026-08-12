"""
    TEST violation fixture: non-trivial branching logic trapped in a
    static method that callers invoke directly by name, with no
    injection point through which a test could substitute different
    pricing behavior.
"""


class ShippingCostCalculator:
    @staticmethod
    def calculate(weight_kg: float, destination_country: str, is_express: bool) -> float:
        if destination_country == "US":
            base = 5.0 if weight_kg <= 2 else 12.0
        elif destination_country == "CA":
            base = 7.0 if weight_kg <= 2 else 15.0
        else:
            base = 20.0 if weight_kg <= 2 else 35.0

        if is_express:
            base *= 1.75

        return base
