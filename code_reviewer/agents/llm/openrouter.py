"""
    LLMInterface implementation backed by OpenRouter's hosted API.
"""
from langchain.agents.structured_output import ProviderStrategy, ResponseFormat

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.config.settings import get_settings

settings = get_settings()

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
        self._model_name = model_name or settings.openrouter_model

    def _get_model_name(self) -> str:
        return self._model_name

    def _get_model_provider(self) -> str:
        return "openrouter"

    def _get_base_url(self) -> str:
        return OPENROUTER_BASE_URL

    def _get_api_key(self) -> str | None:
        return settings.openrouter_api_key

    def build_response_format(self, schema: type[T]) -> ResponseFormat[T]:
        """Use provider-native structured output.
        """
        return ProviderStrategy(schema)
