"""
    Custom Guardrails validator that rejects submissions containing prompt-injection attempts.
"""
from typing import Callable, Optional

from guardrails.validators import register_validator

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.guardrails.validators.base import BaseLLMValidator
from code_reviewer.prompts.intake import PROMPT_INJECTION_SYSTEM_PROMPT


@register_validator(name="prompt-injection", data_type="string")
class PromptInjectionValidator(BaseLLMValidator):
    """Rejects submissions that try to manipulate or redirect a downstream reviewing LLM."""

    def __init__(
        self,
        llm: LLMInterface | None = None,
        on_fail: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            system_prompt=PROMPT_INJECTION_SYSTEM_PROMPT,
            llm=llm,
            on_fail=on_fail,
        )
