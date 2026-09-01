"""
    Concrete class for the SOLID2 agent: Liskov Substitution, Interface
    Segregation, and Dependency Inversion principles.
"""

from langchain.agents.middleware import AgentMiddleware

from code_reviewer.agents.base import FileSizeAwareAgentBase, ReviewContext
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.solid_2 import SOLID2_AGENT_SYSTEM_PROMPT
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.schemas.review import CodeKey


class SolidLspDipAgent(FileSizeAwareAgentBase):
    """Reviews LSP, ISP and DIP: substitution contracts, interface segregation, and dependency direction."""

    def __init__(
        self, llm: LLMInterface | None = None, corpora: ExemplarCorpora | None = None
    ) -> None:
        self._corpora = corpora
        super().__init__(CodeKey.SOLID2, SOLID2_AGENT_SYSTEM_PROMPT, llm)

    def _extra_middleware(self) -> list[AgentMiddleware]:
        if self._corpora is None:
            return []
        return [ExemplarInjection(CodeKey.SOLID2, self._corpora)]

    def _context_schema(self) -> type | None:
        return ReviewContext if self._corpora is not None else None
