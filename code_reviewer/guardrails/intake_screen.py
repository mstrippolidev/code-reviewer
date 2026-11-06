"""
    First point in the pipeline. Screens raw submitted content before it
    reaches file size validation and the 14 review agents.
"""
from guardrails import Guard
from guardrails.errors import ValidationError as GuardrailsValidationError
from guardrails.hub import ProfanityFree

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.guardrails.validators.code_detection import CodeDetectionValidator
from code_reviewer.guardrails.validators.prompt_injection import PromptInjectionValidator

_OTHER_VALIDATOR = "other"
_VALIDATOR_LABELS = {
    "CodeDetectionValidator": "code_detection",
    "PromptInjectionValidator": "prompt_injection",
    "ProfanityFree": "profanity",
}


def build_intake_guard(llm: LLMInterface | None = None) -> Guard:
    """Assembles the intake Guard in cheapest-first order: the local, no-LLM
    profanity check runs before code-detection and prompt-injection, and each
    check raises on failure so later, costlier checks are skipped once one rejects."""
    return Guard().use(
        ProfanityFree(on_fail="exception"),
        CodeDetectionValidator(llm=llm, on_fail="exception"),
        PromptInjectionValidator(llm=llm, on_fail="exception"),
    )


def run_intake_screen(content: str, guard: Guard | None = None, llm: LLMInterface | None = None) -> None:
    """Rejects content that is not source code or that contains a prompt-injection attempt.

    Builds a fresh Guard per call when none is supplied, rather than sharing
    one module-level instance: the orchestrator now screens every file in a
    submission concurrently, and a Guard mutates its own call history on
    every validate() — sharing one across threads would race on that state.
    """
    active_guard = guard if guard is not None else build_intake_guard(llm)
    try:
        active_guard.validate(content, metadata={})
    except GuardrailsValidationError as error:
        raise IntakeRejectedError(str(error), _rejecting_validator(active_guard)) from error


def _rejecting_validator(guard: Guard) -> str:
    """Names the validator that failed, from a fixed set so it is safe as a metric label."""
    try:
        failed_validator = guard.history.last.failed_validations[0].validator_name
        return _VALIDATOR_LABELS.get(failed_validator, _OTHER_VALIDATOR)
    except (AttributeError, IndexError, TypeError):
        return _OTHER_VALIDATOR
