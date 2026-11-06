"""
    Tests that the ARCH/COUP evidence tool reports what each lookup gave back and how long the store took.
    The vector store is a mock, so nothing here touches a database.
"""
from unittest.mock import Mock

import pytest
from langgraph.prebuilt import ToolRuntime
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.agents import cross_file_evidence_tool
from code_reviewer.agents.base import ReviewContext
from code_reviewer.agents.cross_file_evidence_tool import GetFileChunksTool
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_EVIDENCE_LOOKUPS, RAG_RETRIEVAL_DURATION, point_with, points_for

_RESULT_LABEL = "code_reviewer.result"
_SOURCE_LABEL = "code_reviewer.source"
_OUTCOME_LABEL = "code_reviewer.outcome"
_CONTEXT = ReviewContext(repo_id="1", owner_id="7")
_SESSION_CHUNK = FileChunk(
    file_path="infra/db.py", chunk_name="Session", start_line=1, end_line=5, text="opens a session", code="class Session: ..."
)


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the tool at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(cross_file_evidence_tool, "rag_metrics", isolated_rag_metrics)


def _runtime(context: ReviewContext | None) -> ToolRuntime:
    return ToolRuntime(
        state={}, context=context, config={}, stream_writer=lambda *a, **k: None, tool_call_id=None, store=None
    )


def _tool(chunks: list[FileChunk] | Exception) -> tuple[GetFileChunksTool, Mock]:
    rag_manager = Mock(spec=LlamaIndexRagManager)
    if isinstance(chunks, Exception):
        rag_manager.get_file_chunks.side_effect = chunks
    else:
        rag_manager.get_file_chunks.return_value = chunks
    return GetFileChunksTool(rag_manager=rag_manager), rag_manager


def _lookup_count(metric_reader: InMemoryMetricReader, result: str) -> int:
    return point_with(metric_reader, RAG_EVIDENCE_LOOKUPS, {_RESULT_LABEL: result}).value


def test_a_review_without_a_repo_is_counted_as_no_repo(metric_reader: InMemoryMetricReader) -> None:
    """Verify a guest review's lookup is its own series, not an empty or failed one."""
    tool, rag_manager = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(None))

    assert _lookup_count(metric_reader, "no_repo") == 1
    rag_manager.get_file_chunks.assert_not_called()


def test_a_context_with_no_repo_id_is_counted_as_no_repo(metric_reader: InMemoryMetricReader) -> None:
    """Verify a context that exists but names no repo is treated the same way."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(ReviewContext(repo_id=None, owner_id=None)))

    assert _lookup_count(metric_reader, "no_repo") == 1


def test_a_whole_file_lookup_is_counted_as_found(metric_reader: InMemoryMetricReader) -> None:
    """Verify returning the file's content is a hit."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    assert _lookup_count(metric_reader, "found") == 1


def test_a_file_with_nothing_indexed_is_counted_as_empty(metric_reader: InMemoryMetricReader) -> None:
    """Verify "no indexed content" is told apart from a hit, so a stale or unindexed repo shows."""
    tool, _ = _tool([])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    assert _lookup_count(metric_reader, "empty") == 1


def test_a_store_error_is_counted_as_failed_and_the_tool_still_answers(metric_reader: InMemoryMetricReader) -> None:
    """Verify an outage is counted, and the model still gets its fall-back message instead of an exception."""
    tool, _ = _tool(VectorStoreQueryError("store down"))

    answer = tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    assert _lookup_count(metric_reader, "failed") == 1
    assert "Could not look up" in answer


def test_a_symbol_with_an_exact_chunk_is_counted_as_found(metric_reader: InMemoryMetricReader) -> None:
    """Verify narrowing to a definition by name is a hit."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT), imported_symbol_name="Session")

    assert _lookup_count(metric_reader, "found") == 1


def test_a_symbol_found_only_by_text_is_counted_as_found(metric_reader: InMemoryMetricReader) -> None:
    """Verify the text-window fallback also counts as a hit, since the model got evidence."""
    chunk = FileChunk(
        file_path="infra/db.py", chunk_name="helpers", start_line=1, end_line=3, text="", code="x = module.attr()"
    )
    tool, _ = _tool([chunk])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT), imported_symbol_name="attr")

    assert _lookup_count(metric_reader, "found") == 1


def test_a_symbol_that_is_nowhere_in_the_file_is_counted_as_symbol_not_found(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the file was there but the name was not, which points at a wrong import in the reviewed code."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT), imported_symbol_name="Missing")

    assert _lookup_count(metric_reader, "symbol_not_found") == 1


def test_a_real_store_lookup_is_timed_once(metric_reader: InMemoryMetricReader) -> None:
    """Verify a cache miss adds one point to the evidence series."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE_LABEL: "evidence_lookup"}).count == 1


def test_a_cache_hit_is_counted_as_a_lookup_but_not_timed_as_a_search(metric_reader: InMemoryMetricReader) -> None:
    """Verify the second request for a file counts as a hit and leaves the store timer alone."""
    tool, rag_manager = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))
    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    assert _lookup_count(metric_reader, "found") == 2
    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE_LABEL: "evidence_lookup"}).count == 1
    assert rag_manager.get_file_chunks.call_count == 1


def test_a_failed_store_lookup_is_timed_as_failed(metric_reader: InMemoryMetricReader) -> None:
    """Verify the timer records the failing attempt too, since a slow failure is what hurts."""
    tool, _ = _tool(VectorStoreQueryError("store down"))

    tool._run(file_path="infra/db.py", runtime=_runtime(_CONTEXT))

    failed = point_with(
        metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE_LABEL: "evidence_lookup", _OUTCOME_LABEL: "failed"}
    )
    assert failed.count == 1


def test_no_repo_lookup_adds_no_store_timing(metric_reader: InMemoryMetricReader) -> None:
    """Verify a lookup that never reached the store leaves the duration series empty."""
    tool, _ = _tool([_SESSION_CHUNK])

    tool._run(file_path="infra/db.py", runtime=_runtime(None))

    assert points_for(metric_reader, RAG_RETRIEVAL_DURATION) == []
