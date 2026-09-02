from abc import ABC, abstractmethod
from decimal import Decimal


class LateFeePolicy(ABC):
    """Contract for deciding what a customer owes on an overdue invoice."""

    @abstractmethod
    def fee_for(self, balance: Decimal, days_late: int) -> Decimal:
        ...


class FlatLateFeePolicy(LateFeePolicy):
    """Charges one fixed amount however long an invoice is overdue."""

    def __init__(self, amount: Decimal) -> None:
        self._amount = amount

    def fee_for(self, balance: Decimal, days_late: int) -> Decimal:
        return self._amount


class DailyLateFeePolicy(LateFeePolicy):
    """Charges a percentage of the balance for each day an invoice is overdue."""

    def __init__(self, daily_rate: Decimal) -> None:
        self._daily_rate = daily_rate

    def fee_for(self, balance: Decimal, days_late: int) -> Decimal:
        return balance * self._daily_rate * days_late


class LateFeeCalculator:
    """Applies a caller-chosen late fee policy to an overdue balance."""

    def __init__(self, policy: LateFeePolicy) -> None:
        self._policy = policy

    def total_owed(self, balance: Decimal, days_late: int) -> Decimal:
        if days_late <= 0:
            return balance
        return balance + self._policy.fee_for(balance, days_late)
