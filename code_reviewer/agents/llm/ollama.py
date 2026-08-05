"""
    LLMInterface implementation backed by a local Ollama instance.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.config.settings import get_settings

settings = get_settings()


class OllamaLLM(LLMInterface[T]):
    """Builds chat models backed by a local Ollama instance."""

    def __init__(self, temperature: float = 0.2) -> None:
        self._temperature = temperature

    def create_model(self, output_schema: type[T]) -> Runnable[LanguageModelInput, T]:
        """Build the chat model for the current environment, bound to output_schema.

        Returns:
            A Runnable whose invoke() returns an already-parsed instance of
            output_schema directly, not a raw AIMessage.
        """
        model = init_chat_model(
            self._get_model_name(),
            temperature=self._temperature,
            model_provider=self._get_model_provider(),
            base_url=self._get_base_url(),
        )
        return model.with_structured_output(output_schema)

    def _get_model_name(self) -> str:
        return settings.ollama_llm_model

    def _get_model_provider(self) -> str:
        return 'ollama'

    def _get_base_url(self) -> str:
        return settings.ollama_base_url
