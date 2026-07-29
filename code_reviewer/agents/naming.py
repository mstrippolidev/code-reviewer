"""
    VAR agent: reviews naming quality of functions, methods, classes, and variables.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.templates import VAR_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class NamingAgent(AgentBase):
    """Reviews naming quality: expressiveness, abbreviations, and vocabulary consistency."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.VAR, VAR_AGENT_SYSTEM_PROMPT, llm)