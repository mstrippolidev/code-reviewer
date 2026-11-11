"""
    SOLID1 gray-area fixture: a match over a small closed enum of three
    statuses. A new status means a new case here, but the set is fixed and
    small, so extracting polymorphism may be more than the code needs.
"""
from enum import Enum


class OrderStatus(Enum):
    PENDING = "pending"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


def status_label(status: OrderStatus) -> str:
    match status:
        case OrderStatus.PENDING:
            return "Waiting to ship"
        case OrderStatus.SHIPPED:
            return "On its way"
        case OrderStatus.CANCELLED:
            return "Cancelled"
