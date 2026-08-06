"""
    Concrete class for the SOLID2 agent: Liskov Substitution, Interface
    Segregation, and Dependency Inversion principles.
"""

from code_reviewer.agents.base import FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.templates import SOLID2_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class SolidLspDipAgent(FileSizeAwareAgentBase):
    """Reviews LSP, ISP, and DIP: substitution contracts, interface segregation, and dependency inversion."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.SOLID2, SOLID2_AGENT_SYSTEM_PROMPT, llm)
