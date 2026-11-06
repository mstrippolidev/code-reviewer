"""
    Middleware that times and counts every real model call of one agent, retries included.
"""
from collections.abc import Callable
from enum import StrEnum

import httpx
import ollama
import openai
from langchain.agents.middleware import AgentMiddleware, ModelRequest, wrap_model_call
from langchain.agents.middleware.types import ExtendedModelResponse, ModelCallResult
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage, BaseMessage

from code_reviewer.agents.llm.middleware import StructuredOutputNotCalledError
from code_reviewer.agents.llm.timeout import raise_if_deadline_passed
from code_reviewer.telemetry.metrics import pipeline_metrics
from code_reviewer.telemetry.run_summary import usage_of


class LlmErrorCause(StrEnum):
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    SCHEMA_INVALID = "schema_invalid"
    NO_TOOL_CALL = "no_tool_call"
    OTHER = "other"


_CAUSES_BY_TYPE = (
    (openai.APITimeoutError, LlmErrorCause.TIMEOUT),
    (httpx.TimeoutException, LlmErrorCause.TIMEOUT),
    (TimeoutError, LlmErrorCause.TIMEOUT),
    (openai.RateLimitError, LlmErrorCause.RATE_LIMIT),
    (openai.InternalServerError, LlmErrorCause.SERVER_ERROR),
    (openai.APIConnectionError, LlmErrorCause.CONNECTION),
    (httpx.TransportError, LlmErrorCause.CONNECTION),
    (ConnectionError, LlmErrorCause.CONNECTION),
    (StructuredOutputValidationError, LlmErrorCause.SCHEMA_INVALID),
    (StructuredOutputNotCalledError, LlmErrorCause.NO_TOOL_CALL),
)

_OLLAMA_CONNECTION_STATUS = -1
_OLLAMA_RATE_LIMIT_STATUS = 429
_FIRST_SERVER_ERROR_STATUS = 500


def classify_llm_error(error: BaseException) -> str:
    """Names why a model call failed, from a fixed set so it is safe to use as a metric label."""
    if isinstance(error, ollama.ResponseError):
        return _cause_for_ollama_status(error.status_code).value
    for error_type, cause in _CAUSES_BY_TYPE:
        if isinstance(error, error_type):
            return cause.value
    return LlmErrorCause.OTHER.value


def build_model_call_observer(code_key: str, model_name: str) -> AgentMiddleware:
    """Builds the middleware that records latency, concurrency, tokens and failure cause for one caller's model calls."""

    @wrap_model_call
    def observe_model_call(
        request: ModelRequest, handler: Callable[[ModelRequest], ModelCallResult]
    ) -> ModelCallResult:
        raise_if_deadline_passed()
        with pipeline_metrics.track_llm_call(code_key, model_name, classify_llm_error):
            response = handler(request)
        pipeline_metrics.record_llm_usage(code_key, model_name, usage_of(_messages_of(response)))
        return response

    return observe_model_call


def _messages_of(response: ModelCallResult) -> list[BaseMessage]:
    """The messages inside any of the three shapes a model call handler can return."""
    if isinstance(response, AIMessage):
        return [response]
    if isinstance(response, ExtendedModelResponse):
        return response.model_response.result
    return response.result


def _cause_for_ollama_status(status_code: int) -> LlmErrorCause:
    """Maps an Ollama HTTP status to the same causes the OpenAI client's exceptions give."""
    if status_code == _OLLAMA_CONNECTION_STATUS:
        return LlmErrorCause.CONNECTION
    if status_code == _OLLAMA_RATE_LIMIT_STATUS:
        return LlmErrorCause.RATE_LIMIT
    if status_code >= _FIRST_SERVER_ERROR_STATUS:
        return LlmErrorCause.SERVER_ERROR
    return LlmErrorCause.OTHER
