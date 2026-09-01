"""
    Concrete class for the COH agent: cohesion within a class or module.
"""

from langchain.agents.middleware import AgentMiddleware

from code_reviewer.agents.base import FileSizeAwareAgentBase, ReviewContext
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.cohesion import COH_AGENT_SYSTEM_PROMPT
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.schemas.review import CodeKey


class CohesionAgent(FileSizeAwareAgentBase):
    """Reviews cohesion: whether a class or module's members share the same data and purpose."""

    def __init__(
        self, llm: LLMInterface | None = None, corpora: ExemplarCorpora | None = None
    ) -> None:
        self._corpora = corpora
        super().__init__(CodeKey.COH, COH_AGENT_SYSTEM_PROMPT, llm)

    def _extra_middleware(self) -> list[AgentMiddleware]:
        if self._corpora is None:
            return []
        return [ExemplarInjection(CodeKey.COH, self._corpora)]

    def _context_schema(self) -> type | None:
        return ReviewContext if self._corpora is not None else None
