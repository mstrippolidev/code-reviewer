"""
    COH priority=medium fixture: methods split into two disjoint clusters
    by which attributes they touch — the cart methods never read or write
    the notification-preference attributes, and vice versa.
"""


class AccountSession:
    def __init__(self) -> None:
        self._cart_items: list[str] = []
        self._cart_total = 0.0
        self._email_opt_in = True
        self._sms_opt_in = False

    def add_to_cart(self, item: str, price: float) -> None:
        self._cart_items.append(item)
        self._cart_total += price

    def cart_total(self) -> float:
        return self._cart_total

    def clear_cart(self) -> None:
        self._cart_items = []
        self._cart_total = 0.0

    def enable_email_notifications(self) -> None:
        self._email_opt_in = True

    def disable_email_notifications(self) -> None:
        self._email_opt_in = False

    def enable_sms_notifications(self) -> None:
        self._sms_opt_in = True

    def notification_summary(self) -> str:
        return f"email={self._email_opt_in} sms={self._sms_opt_in}"
