"""
    CMT agent: reviews comment and docstring quality.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.comments import COMMENTS_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class CommentsAgent(AgentBase):
    """Reviews comment quality: redundancy, staleness, commented-out code, and docstring scope."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.CMT, COMMENTS_AGENT_SYSTEM_PROMPT, llm)