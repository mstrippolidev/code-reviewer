from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Parcel:
    weight_kg: float
    destination_zone: str


class RateTable(ABC):
    """Prices a parcel; the only thing the quote needs to know about rates."""

    @abstractmethod
    def price_cents(self, parcel: Parcel) -> int:
        ...


class ZoneRateTable(RateTable):
    def __init__(self, cents_per_kg_by_zone: dict[str, int]) -> None:
        self._cents_per_kg_by_zone = cents_per_kg_by_zone

    def price_cents(self, parcel: Parcel) -> int:
        return round(self._cents_per_kg_by_zone[parcel.destination_zone] * parcel.weight_kg)


class ShippingQuote:
    """Quotes a parcel. Depends on the rate table through its public method
    only, receives it from outside, and is never referenced by it."""

    def __init__(self, rates: RateTable, handling_fee_cents: int) -> None:
        self._rates = rates
        self._handling_fee_cents = handling_fee_cents

    def total_cents(self, parcel: Parcel) -> int:
        return self._rates.price_cents(parcel) + self._handling_fee_cents
