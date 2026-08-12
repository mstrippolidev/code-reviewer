"""
    Concrete class for the COUP agent: coupling between units.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.coupling import COUP_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class CouplingAgent(FileSizeAwareAgentBase):
    """Reviews coupling: how units depend on each other, in which direction,
    and how far past each other's public surface they reach."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.COUP, COUP_AGENT_SYSTEM_PROMPT, llm)
