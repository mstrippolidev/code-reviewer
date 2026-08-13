"""
    Concrete class for the CONC agent: concurrency safety.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.concurrency import CONC_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class ConcurrencyAgent(AgentBase):
    """Reviews concurrency safety: dangerous behavior under concurrent access, and proposes solutions."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.CONC, CONC_AGENT_SYSTEM_PROMPT, llm)
