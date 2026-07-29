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


def build_intake_guard(llm: LLMInterface | None = None) -> Guard:
    """Assembles the intake Guard in cheapest-first order: the local, no-LLM
    profanity check runs before code-detection and prompt-injection, and each
    check raises on failure so later, costlier checks are skipped once one rejects."""
    return Guard().use(
        ProfanityFree(on_fail="exception"),
        CodeDetectionValidator(llm=llm, on_fail="exception"),
        PromptInjectionValidator(llm=llm, on_fail="exception"),
    )


_default_guard = build_intake_guard()


def run_intake_screen(content: str, guard: Guard | None = None) -> None:
    """Rejects content that is not source code or that contains a prompt-injection attempt."""
    active_guard = guard if guard is not None else _default_guard
    try:
        active_guard.validate(content, metadata={})
    except GuardrailsValidationError as error:
        raise IntakeRejectedError(str(error)) from error
