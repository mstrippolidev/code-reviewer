"""
    Corrective retry middleware: on a structured-output validation failure,
    re-prompts the model with its own invalid response so it can fix the
    mistake, instead of retrying blind with an unchanged request.
"""
from typing import Callable

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import HumanMessage

MAX_RETRIES = 2


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
