"""
    TEST violation fixture: a constructor requiring clearly excessive
    setup. OrderCheckout takes seven collaborators to build, so exercising
    one piece of checkout behavior means wiring up far more than that
    behavior actually touches.
"""


class InventoryClient:
    def reserve(self, sku: str) -> None: ...


class PricingEngine:
    def price_for(self, sku: str) -> float:
        return 0.0


class TaxService:
    def tax_for(self, amount: float) -> float:
        return 0.0


class ShippingEstimator:
    def estimate(self, address: str) -> float:
        return 0.0


class FraudScorer:
    def score(self, order_id: str) -> float:
        return 0.0


class LoyaltyPointsLedger:
    def points_for(self, amount: float) -> int:
        return 0


class NotificationDispatcher:
    def notify(self, order_id: str) -> None: ...


class OrderCheckout:
    def __init__(
        self,
        inventory: InventoryClient,
        pricing: PricingEngine,
        tax: TaxService,
        shipping: ShippingEstimator,
        fraud: FraudScorer,
        loyalty: LoyaltyPointsLedger,
        notifications: NotificationDispatcher,
    ) -> None:
        self._inventory = inventory
        self._pricing = pricing
        self._tax = tax
        self._shipping = shipping
        self._fraud = fraud
        self._loyalty = loyalty
        self._notifications = notifications

    def checkout(self, sku: str, address: str) -> float:
        self._inventory.reserve(sku)
        price = self._pricing.price_for(sku)
        total = price + self._tax.tax_for(price) + self._shipping.estimate(address)
        self._notifications.notify(sku)
        return total
