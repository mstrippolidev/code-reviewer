"""
    COUP gray-area fixture: a method that reads two public fields of a parcel
    and one value of its own. It leans towards the parcel's data without
    manipulating it, so whether it is feature envy is a judgment call.
"""
from dataclasses import dataclass


@dataclass
class Parcel:
    weight_kg: float
    destination: str


class ShippingLabel:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def describe(self, parcel: Parcel) -> str:
        return f"{self._prefix}-{parcel.weight_kg}kg-{parcel.destination}"
