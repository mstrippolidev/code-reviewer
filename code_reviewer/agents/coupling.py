"""
    Concrete class for the COUP agent: coupling between units.
"""

from langchain.agents.middleware import AgentMiddleware
from langchain_core.tools import BaseTool

from code_reviewer.agents.base import FileSizeAwareAgentBase, ReviewContext, recursion_limit_for_tool_calls
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.coupling import COUP_AGENT_REPOLESS_SYSTEM_PROMPT, COUP_AGENT_SYSTEM_PROMPT
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.schemas.review import CodeKey

_MAX_EVIDENCE_LOOKUPS = 3


class CouplingAgent(FileSizeAwareAgentBase):
    """Reviews coupling: how units depend on each other, in which direction,
    and how far past each other's public surface they reach."""

    def __init__(
        self,
        llm: LLMInterface | None = None,
        rag_manager: LlamaIndexRagManager | None = None,
        corpora: ExemplarCorpora | None = None,
    ) -> None:
        self._rag_manager = rag_manager
        self._corpora = corpora
        prompt = COUP_AGENT_SYSTEM_PROMPT if rag_manager is not None else COUP_AGENT_REPOLESS_SYSTEM_PROMPT
        super().__init__(CodeKey.COUP, prompt, llm)

    def _build_tools(self) -> list[BaseTool] | None:
        if self._rag_manager is None:
            return None
        return [GetFileChunksTool(rag_manager=self._rag_manager)]

    def _extra_middleware(self) -> list[AgentMiddleware]:
        if self._corpora is None:
            return []
        return [ExemplarInjection(CodeKey.COUP, self._corpora)]

    def _context_schema(self) -> type | None:
        if self._rag_manager is None and self._corpora is None:
            return None
        return ReviewContext

    def _recursion_limit(self) -> int:
        if self._rag_manager is None:
            return super()._recursion_limit()
        return recursion_limit_for_tool_calls(_MAX_EVIDENCE_LOOKUPS)
