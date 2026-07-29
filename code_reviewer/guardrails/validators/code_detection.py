"""
    Custom Guardrails validator that rejects submissions which are not source code.
"""
from typing import Callable, Optional

from guardrails.validators import register_validator

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.guardrails.validators.base import BaseLLMValidator
from code_reviewer.prompts.templates import CODE_DETECTION_SYSTEM_PROMPT


@register_validator(name="code-detection", data_type="string")
class CodeDetectionValidator(BaseLLMValidator):
    """Rejects submissions that are not source code, in any language."""

    def __init__(
        self,
        llm: LLMInterface | None = None,
        on_fail: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            system_prompt=CODE_DETECTION_SYSTEM_PROMPT,
            llm=llm,
            on_fail=on_fail,
        )
