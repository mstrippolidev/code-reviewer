"""
    COUP violation fixture: a god object. ApplicationController instantiates
    seven unrelated collaborators and every operation routes through it, so
    no part of the system can move without touching this class.
"""


class UserRepository:
    def find(self, user_id: str) -> dict:
        return {"id": user_id}


class PaymentGateway:
    def charge(self, amount: float) -> str:
        return f"charged {amount}"


class EmailSender:
    def send(self, to: str, body: str) -> None:
        print(f"{to}: {body}")


class AuditLog:
    def record(self, event: str) -> None:
        print(event)


class InventoryService:
    def reserve(self, sku: str) -> None:
        print(f"reserved {sku}")


class ShippingClient:
    def dispatch(self, address: str) -> None:
        print(f"dispatched to {address}")


class AnalyticsTracker:
    def track(self, event: str) -> None:
        print(event)


class ApplicationController:
    def __init__(self) -> None:
        self._users = UserRepository()
        self._payments = PaymentGateway()
        self._email = EmailSender()
        self._audit = AuditLog()
        self._inventory = InventoryService()
        self._shipping = ShippingClient()
        self._analytics = AnalyticsTracker()

    def place_order(self, user_id: str, sku: str, amount: float) -> None:
        user = self._users.find(user_id)
        self._inventory.reserve(sku)
        self._payments.charge(amount)
        self._shipping.dispatch(user["id"])
        self._email.send(user["id"], "order placed")
        self._audit.record("order placed")
        self._analytics.track("order placed")
