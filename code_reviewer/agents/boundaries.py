"""
    Concrete class for the BOUND agent: encapsulation and information hiding.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.boundaries import BOUND_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class BoundariesAgent(FileSizeAwareAgentBase):
    """Reviews boundaries: what a unit exposes versus hides, and whether
    what crosses its public surface is expressed in its own vocabulary."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.BOUND, BOUND_AGENT_SYSTEM_PROMPT, llm)
