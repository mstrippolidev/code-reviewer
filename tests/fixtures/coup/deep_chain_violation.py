"""
    COUP violation fixture: navigation through a chain of intermediate
    objects. LabelPrinter reaches through Order to Customer to Address to
    Country, so it depends on all four types rather than on the one it was
    given.
"""


class Country:
    def __init__(self, code: str) -> None:
        self.code = code


class Address:
    def __init__(self, street: str, country: Country) -> None:
        self.street = street
        self.country = country


class Customer:
    def __init__(self, name: str, address: Address) -> None:
        self.name = name
        self.address = address


class Order:
    def __init__(self, customer: Customer) -> None:
        self.customer = customer


class LabelPrinter:
    def print_label(self, order: Order) -> str:
        street = order.customer.address.street
        country_code = order.customer.address.country.code
        return f"{order.customer.name}, {street}, {country_code}"
