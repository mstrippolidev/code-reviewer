"""
    Concrete class for the COH agent: cohesion within a class or module.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.cohesion import COH_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class CohesionAgent(FileSizeAwareAgentBase):
    """Reviews cohesion: whether a class or module's members share the same data and purpose."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.COH, COH_AGENT_SYSTEM_PROMPT, llm)
