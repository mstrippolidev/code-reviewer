"""
    Base class for guardrails validators that screen content via one LLM call.
"""
import logging
from typing import Any, Callable, Optional

from guardrails.validators import (
    FailResult,
    PassResult,
    ValidationResult,
    Validator,
)
from langchain_core.prompts import ChatPromptTemplate

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.call_observer import classify_llm_error
from code_reviewer.agents.llm.llm_caller import LlmCaller
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.guardrails.errors import GuardrailsInvocationError
from code_reviewer.schemas.intake import ScreeningVerdict
from code_reviewer.telemetry.metrics import pipeline_metrics
from code_reviewer.telemetry.run_summary import usage_of

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
        self._model_name = llm_factory.model_name
        self._model = llm_factory.create_model(ScreeningVerdict, include_raw=True)

    def _validate(self, value: str, metadata: dict) -> ValidationResult:
        screening_chat = ChatPromptTemplate([
            ("system", self._system_prompt),
            ("human", "{code}"),
        ])
        chain = screening_chat | self._model
        caller = LlmCaller.INTAKE_SCREEN.value
        try:
            with pipeline_metrics.track_llm_call(caller, self._model_name, classify_llm_error):
                result = chain.invoke({"code": value})
            pipeline_metrics.record_llm_usage(caller, self._model_name, usage_of([result["raw"]]))
        except Exception as error:
            logger.exception("%s failed to review the given content.", type(self).__name__)
            raise GuardrailsInvocationError(
                f"{type(self).__name__} failed to review the given content."
            ) from error

        verdict = self._parsed_verdict(result)
        if verdict.is_valid:
            return PassResult()
        logger.warning("%s rejected the content: %s", type(self).__name__, verdict.reason)
        return FailResult(error_message=verdict.reason)

    def _parsed_verdict(self, result: dict[str, Any]) -> ScreeningVerdict:
        """Raises when the model's reply could not be parsed, since include_raw hands that back instead of raising."""
        if result["parsing_error"] is not None or result["parsed"] is None:
            raise GuardrailsInvocationError(
                f"{type(self).__name__} could not parse the model's verdict."
            ) from result["parsing_error"]
        return result["parsed"]
