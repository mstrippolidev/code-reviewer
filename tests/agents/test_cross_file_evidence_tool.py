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


def test_schema_only_exposes_file_path_and_symbol_name_to_the_model() -> None:
    """Verify rag_manager and runtime never leak into what the LLM sees —
    the whole point of injecting them outside the model-visible schema."""
    tool = _make_tool()

    schema = convert_to_openai_tool(tool)

    assert schema["function"]["parameters"]["properties"].keys() == {"file_path", "imported_symbol_name"}


def test_schema_describes_when_to_pass_symbol_name() -> None:
    """Verify the model-visible description explains when to use
    imported_symbol_name, not just its name and type — a bare parameter
    name is not enough for reliable tool use."""
    tool = _make_tool()

    schema = convert_to_openai_tool(tool)

    description = schema["function"]["parameters"]["properties"]["imported_symbol_name"]["description"]
    assert "Optional" in description
    assert len(description) > 40


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


def test_repeated_lookup_of_the_same_file_hits_the_cache_not_the_store() -> None:
    """Verify a second call for the same (repo_id, owner_id, file_path)
    reuses the first call's result instead of querying the vector store
    again — ARCH/COUP routinely re-verify the same file within one review."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py", chunk_name="get_connection", start_line=1, end_line=2, text="...", code="def get_connection():\n    pass"
        )
    ]
    tool = _make_tool(rag_manager)
    context = ReviewContext(repo_id="repo-1", owner_id="owner-1")

    tool._run(file_path="infra/db.py", runtime=_make_runtime(context))
    tool._run(file_path="infra/db.py", runtime=_make_runtime(context))

    rag_manager.get_file_chunks.assert_called_once_with("repo-1", "owner-1", "infra/db.py")


def test_failed_lookup_is_not_cached_and_can_succeed_on_retry() -> None:
    """Verify a transient vector-store failure isn't remembered as
    permanently empty — the next call for the same file must retry the
    store rather than replaying the earlier failure from cache."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.side_effect = [
        VectorStoreQueryError("connection reset"),
        [FileChunk(file_path="infra/db.py", chunk_name="get_connection", start_line=1, end_line=2, text="...", code="def get_connection():\n    pass")],
    ]
    tool = _make_tool(rag_manager)
    context = ReviewContext(repo_id="repo-1", owner_id="owner-1")

    first_result = tool._run(file_path="infra/db.py", runtime=_make_runtime(context))
    second_result = tool._run(file_path="infra/db.py", runtime=_make_runtime(context))

    assert "judge this dependency on what's visible in this file alone" in first_result
    assert "get_connection (1-2):" in second_result
    assert rag_manager.get_file_chunks.call_count == 2


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


def test_symbol_name_exact_match_narrows_to_just_that_chunk() -> None:
    """Verify passing imported_symbol_name filters to the one chunk whose
    name matches exactly, dropping unrelated chunks from the same file."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py",
            chunk_name="Session",
            start_line=1,
            end_line=5,
            text="A database session.",
            code="class Session:\n    pass",
        ),
        FileChunk(
            file_path="infra/db.py",
            chunk_name="unrelated_helper",
            start_line=7,
            end_line=9,
            text="Does something else entirely.",
            code="def unrelated_helper():\n    pass",
        ),
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="Session",
        runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1")),
    )

    assert "Session (1-5):" in result
    assert "unrelated_helper" not in result


def test_symbol_name_with_no_matching_chunk_falls_back_to_a_text_window() -> None:
    """Verify a symbol used as module.attr (no top-level def with that
    exact name) still surfaces a small window around where it appears,
    instead of nothing."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py",
            chunk_name="build_engine",
            start_line=10,
            end_line=20,
            text="Builds the SQLAlchemy engine.",
            code=(
                "def build_engine():\n"
                "    pool = QueuePool()\n"
                "    return create_engine(pool=pool)"
            ),
        )
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="QueuePool",
        runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1")),
    )

    assert "QueuePool" in result
    assert "around line" in result


def test_symbol_name_absent_entirely_returns_a_clear_message() -> None:
    """Verify a symbol name that appears nowhere in the fetched content
    gets an explicit message rather than an empty or misleading result."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py", chunk_name="build_engine", start_line=1, end_line=2, text="...", code="def build_engine():\n    pass"
        )
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="NoSuchSymbol",
        runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1")),
    )

    assert "'NoSuchSymbol' was not found" in result


def test_symbol_name_fallback_matches_whole_words_only() -> None:
    """Verify a short symbol name doesn't false-positive-match as a
    substring of a longer, unrelated identifier."""
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(
            file_path="infra/db.py",
            chunk_name="build",
            start_line=1,
            end_line=3,
            text="...",
            code="def build():\n    session_factory = SessionFactory()\n    return session_factory",
        )
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="Session",
        runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1")),
    )

    assert "'Session' was not found" in result


def test_symbol_name_fallback_caps_the_number_of_occurrences_returned() -> None:
    """Verify a symbol name appearing many times doesn't blow the result
    back up toward whole-file size — the entire point of narrowing."""
    code = "\n".join(f"    call_target({index})" for index in range(20))
    rag_manager = Mock(spec=LlamaIndexRagManager)
    rag_manager.get_file_chunks.return_value = [
        FileChunk(file_path="infra/db.py", chunk_name="build", start_line=1, end_line=20, text="...", code=code)
    ]
    tool = _make_tool(rag_manager)

    result = tool._run(
        file_path="infra/db.py",
        imported_symbol_name="call_target",
        runtime=_make_runtime(ReviewContext(repo_id="repo-1", owner_id="owner-1")),
    )

    assert result.count("around line") == 5
