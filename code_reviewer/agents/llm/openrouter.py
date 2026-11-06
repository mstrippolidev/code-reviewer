"""
    LLMInterface implementation backed by OpenRouter's hosted API.
"""
from typing import Any

import httpx
from langchain.agents.structured_output import ProviderStrategy, ResponseFormat

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import CodeKey

settings = get_settings()


def _fast_code_keys() -> frozenset[str]:
    return frozenset(key.strip() for key in settings.fast_model_agent_keys.split(",") if key.strip())

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_PRICE_TIMEOUT_SECONDS = 10.0


class NonStrictProviderStrategy(ProviderStrategy):
    """OpenAI models behind OpenRouter treat a json_schema with no explicit
    strict flag as strict and reject any schema with defaulted fields, so
    the flag is sent as false instead of being left out."""

    def to_model_kwargs(self) -> dict[str, Any]:
        kwargs = super().to_model_kwargs()
        kwargs["response_format"]["json_schema"]["strict"] = False
        return kwargs


class OpenRouter(LLMInterface[T]):
    """Builds chat models backed by OpenRouter's hosted API."""

    def __init__(self, temperature: float = 0.0, model_name: str | None = None) -> None:
        """Wire this provider to one OpenRouter-hosted model.

        Args:
            temperature: Sampling temperature for the built model.
            model_name: OpenRouter model id to run, e.g. "tencent/hy3".
                Defaults to OPENROUTER_MODEL. Callers that need several
                distinct models at once — a judge panel drawing on
                disjoint model families — name each one explicitly.
        """
        super().__init__(temperature)
        self._explicit_model = model_name is not None
        self._model_name = model_name or settings.openrouter_model

    def for_code_key(self, code_key: CodeKey) -> "OpenRouter[T]":
        if self._explicit_model or code_key.value not in _fast_code_keys():
            return self
        return OpenRouter(temperature=self._temperature, model_name=settings.openrouter_fast_model)

    def for_fast_tier(self) -> "OpenRouter[T]":
        if self._explicit_model:
            return self
        return OpenRouter(temperature=self._temperature, model_name=settings.openrouter_fast_model)

    def fetch_token_prices(self, model_name: str) -> TokenPrices:
        try:
            response = httpx.get(
                f"{OPENROUTER_BASE_URL}/models",
                headers={"Authorization": f"Bearer {self._get_api_key()}"},
                timeout=_PRICE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            models = response.json()["data"]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise PriceUnavailableError("Could not read OpenRouter's model list.") from error
        return _prices_of(model_name, models)

    def _get_model_name(self) -> str:
        return self._model_name

    def _get_model_provider(self) -> str:
        return "openrouter"

    def _get_base_url(self) -> str:
        return OPENROUTER_BASE_URL

    def _get_api_key(self) -> str | None:
        return settings.openrouter_api_key

    def _get_extra_kwargs(self) -> dict[str, Any]:
        """request_timeout is milliseconds here (its own docstring: "Maps
        to SDK timeout_ms"), unlike every other timeout in this project,
        which is always seconds — converted here so settings stays in one
        consistent unit and callers never have to remember this field is
        the exception."""
        return {"request_timeout": int(get_settings().llm_call_timeout_seconds * 1000)}

    def build_response_format(self, schema: type[T]) -> ResponseFormat[T]:
        """Use provider-native structured output.
        """
        return NonStrictProviderStrategy(schema)


def _prices_of(model_name: str, models: list[dict[str, Any]]) -> TokenPrices:
    """Reads one model's prices, which OpenRouter lists as USD-per-token strings; the cache price is optional."""
    entry = next((model for model in models if model.get("id") == model_name), None)
    if entry is None:
        raise PriceUnavailableError(f"OpenRouter does not list {model_name}.")
    try:
        pricing = entry["pricing"]
        cached = pricing.get("input_cache_read")
        return TokenPrices(
            input_per_token=float(pricing["prompt"]),
            output_per_token=float(pricing["completion"]),
            cached_input_per_token=float(cached) if cached is not None else None,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PriceUnavailableError(f"OpenRouter lists {model_name} with prices that cannot be read.") from error
