from abc import ABC, abstractmethod


class SubscriptionReader(ABC):
    """Read access to stored subscriptions, for callers that never write."""

    @abstractmethod
    def find_active(self, customer_id: str) -> list[dict]:
        ...


class SubscriptionWriter(ABC):
    """Write access to stored subscriptions, for callers that never read."""

    @abstractmethod
    def save(self, subscription: dict) -> None:
        ...


class PostgresSubscriptions(SubscriptionReader, SubscriptionWriter):
    """Stores subscriptions in Postgres, serving both halves of the contract."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def find_active(self, customer_id: str) -> list[dict]:
        return self._connection.query(
            "SELECT * FROM subscriptions WHERE customer_id = %s AND active", customer_id
        )

    def save(self, subscription: dict) -> None:
        self._connection.insert("subscriptions", subscription)


class RenewalReminder:
    """Notifies customers whose subscriptions are due to renew.

    Depends on the read half only: it never writes, so it never sees a
    save method it could call by accident.
    """

    def __init__(self, subscriptions: SubscriptionReader, notifier) -> None:
        self._subscriptions = subscriptions
        self._notifier = notifier

    def remind(self, customer_id: str) -> int:
        due = self._subscriptions.find_active(customer_id)
        for subscription in due:
            self._notifier.send(customer_id, subscription["plan"])
        return len(due)
