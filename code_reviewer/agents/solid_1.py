"""
    Concrete class for the SOLID1 agent: Single Responsibility and
    Open/Closed principles.
"""

from langchain.agents.middleware import AgentMiddleware

from code_reviewer.agents.base import FileSizeAwareAgentBase, ReviewContext
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.solid_1 import SOLID1_AGENT_SYSTEM_PROMPT
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.schemas.review import CodeKey


class SolidSrpOcpAgent(FileSizeAwareAgentBase):
    """Reviews SRP and OCP: one reason to change per class/function, and extension without modification."""

    def __init__(
        self, llm: LLMInterface | None = None, corpora: ExemplarCorpora | None = None
    ) -> None:
        self._corpora = corpora
        super().__init__(CodeKey.SOLID1, SOLID1_AGENT_SYSTEM_PROMPT, llm)

    def _extra_middleware(self) -> list[AgentMiddleware]:
        if self._corpora is None:
            return []
        return [ExemplarInjection(CodeKey.SOLID1, self._corpora)]

    def _context_schema(self) -> type | None:
        return ReviewContext if self._corpora is not None else None
