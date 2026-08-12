"""
    CMPLX agent: reviews logic complexity — nesting depth, condition size,
    exit points, and cyclomatic complexity.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.complexity import CMPLX_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class ComplexityAgent(AgentBase):
    """Reviews complexity: nesting depth, boolean condition size, exit points, and cyclomatic complexity."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.CMPLX, CMPLX_AGENT_SYSTEM_PROMPT, llm)
