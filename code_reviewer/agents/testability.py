"""
    Concrete class for the TEST agent: testability and isolation.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.testability import TEST_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class TestabilityAgent(AgentBase):
    """Reviews testability: whether code can be exercised in isolation by a fast unit test."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.TEST, TEST_AGENT_SYSTEM_PROMPT, llm)
