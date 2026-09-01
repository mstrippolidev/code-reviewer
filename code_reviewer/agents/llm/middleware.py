"""
    Corrective retry middleware: on a structured-output validation failure,
    re-prompts the model with its own invalid response so it can fix the
    mistake, instead of retrying blind with an unchanged request.
"""
from typing import Any, Callable

from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    ModelResponse,
    Runtime,
    after_model,
    wrap_model_call,
)
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import HumanMessage

from code_reviewer.schemas.review import AgentReviewEntry, Incident, Priority

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


@after_model
def calculate_rating(state: AgentState, runtime: Runtime) -> dict[str, Any]:
    """Calculate the rating for the agent's output."""
    output = state["structured_response"]
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