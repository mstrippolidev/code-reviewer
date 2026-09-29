"""
    Concrete class for the ARCH agent: layering and dependency direction.
"""

from langchain_core.tools import BaseTool

from code_reviewer.agents.base import FileSizeAwareAgentBase, ReviewContext
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.prompts.agents.architecture import ARCH_AGENT_REPOLESS_SYSTEM_PROMPT, ARCH_AGENT_SYSTEM_PROMPT
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.schemas.review import CodeKey

_TOOL_RECURSION_LIMIT = 10


class ArchitectureAgent(FileSizeAwareAgentBase):
    """Reviews architecture: which layer a unit sits in, which way its
    dependencies point, and whether construction is kept apart from use."""

    def __init__(self, llm: LLMInterface | None = None, rag_manager: LlamaIndexRagManager | None = None) -> None:
        self._rag_manager = rag_manager
        prompt = ARCH_AGENT_SYSTEM_PROMPT if rag_manager is not None else ARCH_AGENT_REPOLESS_SYSTEM_PROMPT
        super().__init__(CodeKey.ARCH, prompt, llm)

    def _build_tools(self) -> list[BaseTool] | None:
        if self._rag_manager is None:
            return None
        return [GetFileChunksTool(rag_manager=self._rag_manager)]

    def _context_schema(self) -> type | None:
        return ReviewContext if self._rag_manager is not None else None

    def _recursion_limit(self) -> int:
        return _TOOL_RECURSION_LIMIT if self._rag_manager is not None else super()._recursion_limit()
