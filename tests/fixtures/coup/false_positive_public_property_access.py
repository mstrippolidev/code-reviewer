"""
    COUP false-positive fixture: reading another object's public,
    non-underscore attribute. Should NOT be flagged as inappropriate
    intimacy — item 3 targets reaching past a private, underscore-marked
    surface or depending on internal shape, not reading a declared public
    field.
"""


class Customer:
    def __init__(self, name: str) -> None:
        self.name = name


class GreetingCard:
    def message_for(self, customer: Customer) -> str:
        return f"Dear {customer.name},"
