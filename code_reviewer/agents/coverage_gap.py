"""
    TCASE agent: reviews test coverage — reads the submission's paired
    test files, when present, and proposes tests only for the gaps.
"""

from code_reviewer.agents.base import AgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.prompts.agents.coverage_gap import TCASE_AGENT_SYSTEM_PROMPT
from code_reviewer.schemas.review import CodeKey


class CoverageGapAgent(AgentBase):
    """Reviews test coverage: proposes tests only for paths, edge cases, and concurrent cases nothing already asserts."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.TCASE, TCASE_AGENT_SYSTEM_PROMPT, llm or OllamaLLM(temperature=0.0))
