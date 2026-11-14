"""
    COUP fixture demonstrating healthy coupling: the dependency runs one
    way, is handed in rather than reached for, and every call goes through
    a public method. None of this should be flagged.
"""


class ShippingRates:
    """Owns the rate table and the arithmetic over it."""

    def __init__(self, base_rate: float) -> None:
        self._base_rate = base_rate

    def cost_for_weight(self, weight_kg: float) -> float:
        return self._base_rate * weight_kg


class ShipmentQuote:
    """Quotes a shipment, delegating rate arithmetic to ShippingRates."""

    def __init__(self, rates: ShippingRates) -> None:
        self._rates = rates
        self._weight_kg = 0.0

    def set_weight(self, weight_kg: float) -> None:
        self._weight_kg = weight_kg

    def total(self) -> float:
        return self._rates.cost_for_weight(self._weight_kg)
