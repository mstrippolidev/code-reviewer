"""
    Concrete class for the SOLID1 agent: Single Responsibility and
    Open/Closed principles.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.solid_1 import SOLID1_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class SolidSrpOcpAgent(FileSizeAwareAgentBase):
    """Reviews SRP and OCP: one reason to change per class/function, and extension without modification."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.SOLID1, SOLID1_AGENT_SYSTEM_PROMPT, llm)
