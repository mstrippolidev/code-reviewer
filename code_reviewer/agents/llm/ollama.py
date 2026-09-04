"""
    LLMInterface implementation backed by a local Ollama instance.
"""
from typing import Any

from langchain.agents.structured_output import ProviderStrategy, ResponseFormat

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.config.settings import get_settings

settings = get_settings()


class OllamaLLM(LLMInterface[T]):
    """Builds chat models backed by a local Ollama instance."""

    def _get_model_name(self) -> str:
        return settings.ollama_llm_model

    def _get_model_provider(self) -> str:
        return "ollama"

    def _get_base_url(self) -> str:
        return settings.ollama_base_url

    def _get_timeout_kwargs(self) -> dict[str, Any]:
        """Ollama has no top-level timeout field — ChatOllama forwards
        client_kwargs to the underlying ollama/httpx client instead."""
        timeout = get_settings().llm_call_timeout_seconds
        return {"client_kwargs": {"timeout": timeout}}

    def build_response_format(self, schema: type[T]) -> ResponseFormat[T]:
        """Use provider-native structured output instead of a tool call.

        Ollama's chat API has no tool_choice forcing, so a model can
        silently decline to call a structured-output tool. Grammar-constrained
        decoding guarantees schema-shaped output regardless of whether the
        model would have volunteered a tool call.
        """
        return ProviderStrategy(schema)