"""
    Tests for GetFileChunksTool: the ARCH/COUP multi-hop evidence tool.
    No LLM involved — these exercise the tool's own logic and its
    LLM-visible schema directly, via a hand-built ToolRuntime instead of
    a real agent loop.
"""
from unittest.mock import Mock

from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.prebuilt import ToolRuntime

from code_reviewer.agents.base import ReviewContext
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager


def _make_runtime(context: ReviewContext | None) -> ToolRuntime:
    return ToolRuntime(
        state={}, context=context, config={}, stream_writer=lambda *a, **k: None, tool_call_id=None, store=None
    )


def _make_tool(rag_manager: Mock | None = None) -> GetFileChunksTool:
    return GetFileChunksTool(rag_manager=rag_manager or Mock(spec=LlamaIndexRagManager))


def test_schema_only_exposes_file_path_to_the_model() -> None:
    """Verify rag_manager and runtime never leak into what the LLM sees —
    the whole point of injecting them outside the model-visible schema."""
    tool = _make_tool()

    schema = convert_to_openai_tool(tool)

    assert schema["function"]["parameters"]["properties"].keys() == {"file_path"}


def test_no_context_returns_the_no_repo_context_message() -> None:
    """Verify a standalone review with no repo context at all (context=None
    never passed to invoke) falls back gracefully instead of crashing."""
    tool = _make_tool()

    result = tool._run(file_path="infra/db.py", runtime=_make_runtime(None))

    assert result == (
        "No repository context available for this review — judge this "
        "dependency on what's visible in this file alone."
    )


def test_context_with_no_repo_id_returns_the_no_repo_context_message() -> None:
    """Verify a ReviewContext with repo_id=None (constructed but empty)
    gets the same fallback as no context at all."""
    tool = _make_tool()

    result = tool._run(file_path="infra/db.py", runtime=_make_runtime(ReviewContext(repo_id=None)))

    assert "No repository context available" in result


def test_found_chunks_are_formatted_with_explanation_and_code() -> None:
    """Verify a real lookup result surfaces both the explanation and the
    raw code per chunk, in the format ARCH/COUP need to re-reason."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py",
            chunk_name="get_connection",
            start_line=1,
            end_line=5,
            text="Opens a raw database connection.",
            code="def get_connection():\n    return psycopg2.connect(...)",
        )
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py", runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1"))
    )

    assert "get_connection (1-5):" in result
    assert "Opens a raw database connection." in result
    assert "----------------------" in result
    assert "def get_connection():" in result
    rag_manager.get_file_chunks.assert_called_once_with("repo-1", "owner-1", "infra/db.py")


def test_no_matching_chunks_reports_nothing_indexed() -> None:
    """Verify a third-party/stdlib import (or anything simply not indexed)
    gets a clear message instead of an empty, ambiguous string."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = []
    tool = _make_tool(rag_manager)

    result = tool._run(file_path="os.py", runtime=_make_runtime(ReviewContext(repo_id="repo-1")))

    assert result == "No indexed content found for 'os.py'."


def test_lookup_failure_falls_back_instead_of_raising() -> None:
    """Verify a vector store failure mid-review degrades to single-file
    judgment rather than crashing the whole agent call."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.side_effect = VectorStoreQueryError("connection reset")
    tool = _make_tool(rag_manager)

    result = tool._run(file_path="infra/db.py", runtime=_make_runtime(ReviewContext(repo_id="repo-1")))

    assert "judge this dependency on what's visible in this file alone" in result
