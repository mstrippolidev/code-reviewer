"""
    Corrective retry middleware: on a structured-output validation failure,
    re-prompts the model with its own invalid response so it can fix the
    mistake, instead of retrying blind with an unchanged request.
"""
from typing import Any, Callable

import httpx
import ollama
import openai
from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    Runtime,
    ToolCallRequest,
    after_model,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import HumanMessage, ToolMessage

from code_reviewer.schemas.review import AgentReviewEntry, Incident, Priority

_ALREADY_CALLED_MESSAGE = (
    "You already called this tool with these exact arguments earlier in "
    "this review — see the result above. Do not call it again with the "
    "same arguments; use what you already have to finalize your answer."
)

MAX_RETRIES = 2

PRIORITY_DISCOUNTS = {
    Priority.CRITICAL: 20,
    Priority.HIGH: 15,
    Priority.MEDIUM: 7,
    Priority.LOW: 3,
}


@wrap_model_call
def retry_model(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Retry a failed structured-output call up to MAX_RETRIES times.

    StructuredOutputValidationError is raised by both ProviderStrategy and
    ToolStrategy, so this applies unchanged regardless of which provider's
    LLMInterface built the agent.

    Raises:
        StructuredOutputValidationError: If the model still fails after
            MAX_RETRIES corrective retries.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return handler(request)
        except StructuredOutputValidationError as error:
            if attempt == MAX_RETRIES:
                raise
            request = _append_correction(request, error)
    raise RuntimeError("Unreachable: retry loop completed without returning.")


def _append_correction(
    request: ModelRequest, error: StructuredOutputValidationError
) -> ModelRequest:
    """Append the model's invalid response plus a corrective instruction."""
    correction = HumanMessage(
        f"Your last response was invalid: {error} "
        "Return a corrected response that fixes this."
    )
    return request.override(messages=[*request.messages, error.ai_message, correction])


class StructuredOutputNotCalledError(Exception):
    """Raised when a tool-carrying agent answers in plain text instead of
    calling any tool, including the structured-output tool, and still hasn't
    after MAX_RETRIES corrective retries."""


_NO_TOOL_CALL_CORRECTION = (
    "Your last response was plain text with no tool call. You must call the "
    "structured-output tool to submit your final review — do not describe it "
    "in words instead."
)


@wrap_model_call
def retry_missing_structured_output(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Retry a turn that answered in plain text instead of calling any tool.

    Raises:
        StructuredOutputNotCalledError: If the model still hasn't called any
            tool after MAX_RETRIES corrective retries.
    """
    for attempt in range(MAX_RETRIES + 1):
        response = handler(request)
        if response.structured_response is not None or _made_a_tool_call(response):
            return response
        if attempt == MAX_RETRIES:
            raise StructuredOutputNotCalledError(
                f"Model did not call any tool after {MAX_RETRIES} corrective retries."
            )
        request = _append_no_tool_call_correction(request, response)
    raise RuntimeError("Unreachable: retry loop completed without returning.")


def _made_a_tool_call(response: ModelResponse) -> bool:
    return any(getattr(message, "tool_calls", None) for message in response.result)


def _append_no_tool_call_correction(request: ModelRequest, response: ModelResponse) -> ModelRequest:
    correction = HumanMessage(_NO_TOOL_CALL_CORRECTION)
    return request.override(messages=[*request.messages, *response.result, correction])


_TRANSIENT_EXCEPTION_TYPES = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    TimeoutError,
    ConnectionError,
)

_TRANSIENT_OLLAMA_STATUS_CODES = {-1, 429, 500, 502, 503, 504}


def _is_transient_llm_error(error: BaseException) -> bool:
    if isinstance(error, _TRANSIENT_EXCEPTION_TYPES):
        return True
    return isinstance(error, ollama.ResponseError) and error.status_code in _TRANSIENT_OLLAMA_STATUS_CODES


retry_transient_call = ModelRetryMiddleware(max_retries=2, retry_on=_is_transient_llm_error, on_failure="error")


@wrap_tool_call
def dedupe_tool_calls(request: ToolCallRequest, handler: Callable) -> ToolMessage:
    """Short-circuits a tool call that exactly repeats one already in this
    conversation, instead of re-executing it. A model without a reasoning
    trace can lose track of having already retrieved something and keep
    re-asking rather than converging on a final answer — this is a
    preventive guard against that, not just the recursion_limit backstop."""
    if _already_called(request):
        return ToolMessage(content=_ALREADY_CALLED_MESSAGE, tool_call_id=request.tool_call["id"])
    return handler(request)


def _already_called(request: ToolCallRequest) -> bool:
    """A message carrying the current call is already committed to state
    by the time this runs, so it has to be excluded by id — otherwise
    every call would match itself and short-circuit before ever running."""
    current_id = request.tool_call["id"]
    current = (request.tool_call["name"], _freeze(request.tool_call["args"]))
    for message in request.state["messages"]:
        for call in getattr(message, "tool_calls", None) or []:
            if call["id"] == current_id:
                continue
            if (call["name"], _freeze(call["args"])) == current:
                return True
    return False


def _freeze(args: dict[str, Any]) -> tuple:
    return tuple(sorted(args.items()))


@after_model
def calculate_rating(state: AgentState, runtime: Runtime) -> dict[str, Any]:
    """Calculate the rating for the agent's output. A turn that emitted a
    tool call has no structured output to rate yet."""
    output = state.get("structured_response")
    if output is None:
        return {}
    for review in output.review:
        review.rating = _calculate_rating_for_review(review)
    return {"structured_response": output}


def _calculate_rating_for_review(review: AgentReviewEntry) -> int:
    """Calculate the rating for one review entry."""
    return rating_from_incidents(review.incidents)


def rating_from_incidents(incidents: list[Incident]) -> int:
    """Shared discount formula: every caller recomputing a rating from a
    (possibly merged or edited) incident list uses this one function, so
    the discount values never drift between the model-facing middleware,
    chunk-merging in dispatch, and consensus's critical-downgrade path."""
    rating = 100
    for incident in incidents:
        rating -= PRIORITY_DISCOUNTS[incident.priority]
    return max(rating, 0)