"""
    LLMInterface implementation backed by OpenRouter's hosted API.
"""
from typing import Any

from langchain.agents.structured_output import ProviderStrategy, ResponseFormat

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import CodeKey

settings = get_settings()


def _fast_code_keys() -> frozenset[str]:
    return frozenset(key.strip() for key in settings.fast_model_agent_keys.split(",") if key.strip())

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


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
        return ProviderStrategy(schema)
