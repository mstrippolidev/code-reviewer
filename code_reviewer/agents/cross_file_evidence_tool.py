"""
    LangChain tool wrapping LlamaIndexRagManager.get_file_chunks for the
    ARCH/COUP multi-hop evidence pass. file_path is the only argument the
    model supplies; repo scoping arrives via the immutable per-invocation
    ToolRuntime.context, never something the model can see or set itself.
"""
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool

from code_reviewer.agents.base import ReviewContext
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager

_NO_REPO_CONTEXT = (
    "No repository context available for this review — judge this "
    "dependency on what's visible in this file alone."
)


class GetFileChunksTool(BaseTool):
    """Fetches another file's indexed content by exact path, so ARCH/COUP
    can verify what a suspicious dependency actually does before
    finalizing a finding. rag_manager is constructor-injected and shared
    across every call this tool makes; repo scoping arrives per call via
    ToolRuntime.context instead."""

    name: str = "get_file_chunks"
    description: str = (
        "Fetch another file's indexed explanation and source code by its "
        "exact path, to verify what a suspicious import or dependency "
        "actually does before finalizing a finding."
    )
    rag_manager: LlamaIndexRagManager

    def _run(self, file_path: str, runtime: ToolRuntime[ReviewContext]) -> str:
        context = runtime.context
        if context is None or context.repo_id is None:
            return _NO_REPO_CONTEXT

        try:
            chunks = self.rag_manager.get_file_chunks(context.repo_id, context.owner_id, file_path)
        except VectorStoreQueryError:
            return (
                f"Could not look up {file_path!r} right now — judge this "
                "dependency on what's visible in this file alone."
            )

        if not chunks:
            return f"No indexed content found for {file_path!r}."
        return "\n\n".join(_format_chunk(chunk) for chunk in chunks)


def _format_chunk(chunk: FileChunk) -> str:
    return (
        f"{chunk.chunk_name} ({chunk.start_line}-{chunk.end_line}):\n"
        f"{chunk.text}\n----------------------\n{chunk.code}"
    )
