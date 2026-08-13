"""
    Concrete class for the ARCH agent: layering and dependency direction.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.architecture import ARCH_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class ArchitectureAgent(FileSizeAwareAgentBase):
    """Reviews architecture: which layer a unit sits in, which way its
    dependencies point, and whether construction is kept apart from use."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.ARCH, ARCH_AGENT_SYSTEM_PROMPT, llm)
