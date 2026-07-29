"""
    Base class for guardrails validators that screen content via one LLM call.
"""
import logging
from typing import Callable, Optional

from guardrails.validators import (
    FailResult,
    PassResult,
    ValidationResult,
    Validator,
)
from langchain_core.prompts import ChatPromptTemplate

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.guardrails.errors import GuardrailsInvocationError
from code_reviewer.schemas.intake import ScreeningVerdict

logger = logging.getLogger(__name__)

class BaseLLMValidator(Validator):
    """Runs one LLM call against a caller-given system prompt and translates
    the resulting ScreeningVerdict into a Pass/Fail result."""

    def __init__(
        self,
        system_prompt: str,
        llm: LLMInterface | None = None,
        on_fail: Optional[Callable] = None,
    ) -> None:
        super().__init__(on_fail=on_fail)
        self._system_prompt = system_prompt
        llm_factory = llm if llm is not None else OllamaLLM()
        self._model = llm_factory.create_model(ScreeningVerdict)

    def _validate(self, value: str, metadata: dict) -> ValidationResult:
        screening_chat = ChatPromptTemplate([
            ("system", self._system_prompt),
            ("human", "{code}"),
        ])
        chain = screening_chat | self._model
        try:
            verdict = chain.invoke({"code": value})
        except Exception as error:
            logger.exception("%s failed to review the given content.", type(self).__name__)
            raise GuardrailsInvocationError(
                f"{type(self).__name__} failed to review the given content."
            ) from error

        if verdict.is_valid:
            return PassResult()
        return FailResult(error_message=verdict.reason)
