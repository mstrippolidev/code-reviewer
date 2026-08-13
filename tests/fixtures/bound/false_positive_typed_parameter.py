"""
    BOUND false-positive fixture: ShippingLabel takes a well-defined
    dataclass parameter instead of a raw dict or **kwargs, so the
    boundary's contract is explicit from the signature alone. Should NOT
    be flagged as the out-of-scope untyped-boundary case — there is
    nothing implicit here for a reader to trace through call sites for.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    street: str
    city: str
    postal_code: str


class ShippingLabel:
    def render(self, address: Address) -> str:
        return f"{address.street}\n{address.city} {address.postal_code}"
