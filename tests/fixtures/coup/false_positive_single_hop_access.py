"""
    COUP false-positive fixture: one direct collaborator, one attribute
    access. Should NOT be flagged as chain navigation — item 5 targets
    reaching through a chain of intermediate objects
    (order.customer.address.postcode), and there is no chain here, just a
    single hop to a direct collaborator's own field.
"""


class Order:
    def __init__(self, customer_name: str) -> None:
        self.customer_name = customer_name


class ShippingLabel:
    def addressee(self, order: Order) -> str:
        return order.customer_name
