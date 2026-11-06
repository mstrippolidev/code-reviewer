"""
    Shared exceptions for the guardrails intake screen's custom validators.
"""


class GuardrailsInvocationError(Exception):
    """Raised when a guardrails validator's LLM call fails or its output cannot be validated."""


class IntakeRejectedError(Exception):
    """Raised when submitted content fails the intake screen: not source code, or a prompt-injection attempt."""

    def __init__(self, message: str, validator: str = "other") -> None:
        super().__init__(message)
        self.validator = validator
