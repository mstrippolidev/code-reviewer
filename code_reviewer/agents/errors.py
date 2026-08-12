"""
    ERR agent: reviews error handling — custom exceptions, explicit raises,
    dead code, and swallowed exceptions.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.errors import ERR_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class ErrorsAgent(AgentBase):
    """Reviews error handling: custom exceptions, raise-over-return, dead code, and swallowed exceptions."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.ERR, ERR_AGENT_SYSTEM_PROMPT, llm)
