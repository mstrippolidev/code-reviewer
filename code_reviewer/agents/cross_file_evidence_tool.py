"""
    LangChain tool wrapping LlamaIndexRagManager.get_file_chunks for the
    ARCH/COUP multi-hop evidence pass. file_path and imported_symbol_name
    are the only arguments the model supplies; repo scoping arrives via the
    immutable per-invocation ToolRuntime.context, never something the model
    can see or set itself.
"""
import re

from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from code_reviewer.agents.base import ReviewContext
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager

_NO_REPO_CONTEXT = (
    "No repository context available for this review — judge this "
    "dependency on what's visible in this file alone."
)

_FALLBACK_WINDOW_LINES = 5
_FALLBACK_MAX_OCCURRENCES = 5


class GetFileChunksArgs(BaseModel):
    """Model-visible schema for GetFileChunksTool — every field's
    description is written to stand alone, since the model only ever sees
    this, never the surrounding Python.

    runtime is declared here purely so LangGraph's ToolNode detects it and
    injects it: it scans this schema, not _run's signature, once
    args_schema is set. It stays out of what the model sees."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    runtime: ToolRuntime = None

    file_path: str = Field(
        description=(
            "Exact path of the file to fetch, relative to the repo root — the same path "
            "shown in the import statement you're verifying."
        )
    )
    imported_symbol_name: str | None = Field(
        default=None,
        description=(
            "Optional. The specific function or class name the suspicious import refers to "
            '(e.g. for `from infra.db import Session`, pass "Session"). When given, you get '
            "back only that definition instead of the whole file, so pass it whenever you "
            "know the exact name — it keeps what you read focused on what you're actually "
            "judging. Leave it unset when there is no single name to narrow to (a wildcard "
            "import, or a module used as `module.attr` with no specific imported name) — "
            "you still get the file's content either way; this argument only narrows it."
        ),
    )


class GetFileChunksTool(BaseTool):
    """Fetches another file's indexed content by exact path, so ARCH/COUP
    can verify what a suspicious dependency actually does before
    finalizing a finding. rag_manager is constructor-injected and shared
    across every call this tool makes; repo scoping arrives per call via
    ToolRuntime.context instead."""

    name: str = "get_file_chunks"
    description: str = (
        "Fetch another file's indexed explanation and source code by its exact path, to "
        "verify what a suspicious import or dependency actually does before finalizing a "
        "finding. Pass imported_symbol_name whenever you know the specific function or class "
        "name the import refers to, to narrow the result to just that definition."
    )
    args_schema: type[BaseModel] = GetFileChunksArgs
    rag_manager: LlamaIndexRagManager

    def _run(
        self, file_path: str, runtime: ToolRuntime[ReviewContext], imported_symbol_name: str | None = None
    ) -> str:
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
        if imported_symbol_name is None:
            return _format_chunks(chunks)
        return _narrow_to_symbol(chunks, imported_symbol_name, file_path)


def _narrow_to_symbol(chunks: list[FileChunk], symbol_name: str, file_path: str) -> str:
    exact_matches = [chunk for chunk in chunks if chunk.chunk_name == symbol_name]
    if exact_matches:
        return _format_chunks(exact_matches)

    windows = _text_windows_around(chunks, symbol_name)
    if not windows:
        return (
            f"{symbol_name!r} was not found in {file_path!r}'s indexed content — judge this "
            "dependency on what's visible in this file alone."
        )
    return "\n\n".join(windows)


def _text_windows_around(chunks: list[FileChunk], symbol_name: str) -> list[str]:
    """Fallback for when no chunk's own name matches — e.g. `import module`
    then `module.attr.deeper()`, with no single top-level def to match
    exactly. Returns a small window around each occurrence of the name in
    the fetched code, capped so an unusually common short name can't blow
    the result back up to whole-file size."""
    pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
    windows: list[str] = []
    for chunk in chunks:
        lines = chunk.code.splitlines()
        for index, line in enumerate(lines):
            if len(windows) >= _FALLBACK_MAX_OCCURRENCES:
                return windows
            if pattern.search(line):
                windows.append(_window_snippet(chunk, lines, index))
    return windows


def _window_snippet(chunk: FileChunk, lines: list[str], index: int) -> str:
    start = max(0, index - _FALLBACK_WINDOW_LINES)
    end = min(len(lines), index + _FALLBACK_WINDOW_LINES + 1)
    snippet = "\n".join(lines[start:end])
    return f"{chunk.chunk_name} (around line {chunk.start_line + index}):\n{snippet}"


def _format_chunks(chunks: list[FileChunk]) -> str:
    return "\n\n".join(_format_chunk(chunk) for chunk in chunks)


def _format_chunk(chunk: FileChunk) -> str:
    return (
        f"{chunk.chunk_name} ({chunk.start_line}-{chunk.end_line}):\n"
        f"{chunk.text}\n----------------------\n{chunk.code}"
    )
