"""
    COUP gray-area fixture: a function reaching through one intermediate object
    to read a public attribute. It is two hops, which is short of a deep chain
    but longer than a single direct collaborator.
"""
from dataclasses import dataclass


@dataclass
class Customer:
    email: str


@dataclass
class Order:
    customer: Customer


def confirmation_recipient(order: Order) -> str:
    return order.customer.email
