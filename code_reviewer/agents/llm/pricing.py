"""
    Price of a model's tokens as a provider reports it.
"""
from pydantic import BaseModel


class PriceUnavailableError(Exception):
    """Raised when a provider cannot say what a model's tokens cost."""


class TokenPrices(BaseModel, frozen=True):
    """USD per single token; a missing cached price means cached tokens cost the input price."""

    input_per_token: float
    output_per_token: float
    cached_input_per_token: float | None = None

    @classmethod
    def free(cls) -> "TokenPrices":
        """The price of a model that costs nothing per token, such as a local one."""
        return cls(input_per_token=0.0, output_per_token=0.0, cached_input_per_token=0.0)
