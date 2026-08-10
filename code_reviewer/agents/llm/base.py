"""
    Contract for building the chat model each review agent runs against.
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from langchain.agents.structured_output import ResponseFormat
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.runnables import Runnable
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMInterface(ABC, Generic[T]):
    """Builds a chat model bound to a caller-given structured output schema,
    so AgentBase (and the intake validators) can depend on this abstraction
    instead of a concrete provider.

    create_model() is the same for every provider — only the model name,
    provider key, and base URL differ. A concrete provider only implements
    those three hooks; it never repeats the init_chat_model wiring itself.
    """

    def __init__(self, temperature: float = 0.0) -> None:
        self._temperature = temperature

    def create_model(
        self, output_schema: type[T], include_raw: bool = False
    ) -> Runnable[LanguageModelInput, T | dict[str, Any]]:
        """Build a chat model bound to output_schema.

        Args:
            output_schema: The schema the model's output must validate against.
            include_raw: When False (default), the returned Runnable produces
                output_schema directly and raises if parsing fails. When True,
                it never raises — it always returns {"raw", "parsed",
                "parsing_error"}, so the caller can inspect a failure and
                retry with corrective feedback instead of losing the attempt.
        """
        model = self.create_raw_model()
        return model.with_structured_output(output_schema, include_raw=include_raw)

    def create_raw_model(self) -> BaseChatModel:
        """
            Build the bare chat model, with no structured-output binding.
        """
        return init_chat_model(
                    self._get_model_name(),
                    temperature=self._temperature,
                    model_provider=self._get_model_provider(),
                    base_url=self._get_base_url(),
                )


    @abstractmethod
    def _get_model_name(self) -> str:
        """Name of the model to run, e.g. 'deepseek-r1:14b'."""

    @abstractmethod
    def _get_model_provider(self) -> str:
        """LangChain provider key, e.g. 'ollama'."""

    @abstractmethod
    def _get_base_url(self) -> str:
        """Base URL of the provider's API."""

    @abstractmethod
    def build_response_format(self, schema: type[T]) -> ResponseFormat[T]:
        """Response-format strategy for schema, chosen per provider's own
        structured-output capabilities (e.g. forced tool call vs.
        grammar-constrained decoding)."""