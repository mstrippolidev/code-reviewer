"""
    Contract for building the chat model each review agent runs against.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar
from langchain_core.language_models import LanguageModelInput
from langchain_core.runnables import Runnable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class LLMInterface(ABC, Generic[T]):
    """Contract for building a chat model bound to a caller-given structured
    output schema, so AgentBase (and the intake validators) can depend on
    this abstraction instead of a concrete provider."""

    @abstractmethod
    def create_model(self, output_schema: type[T]) -> Runnable[LanguageModelInput, T]:
        """Build and return a chat model bound to output_schema."""
