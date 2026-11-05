"""
    Tests that DRY counts the candidates that survived re-ranking, by the search that found them.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.pipeline import dry_check
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import StructuralMatch
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_DRY_CANDIDATES, point_with

_SOURCE = "code_reviewer.source"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points DRY's workflow at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(dry_check, "rag_metrics", isolated_rag_metrics)


def _match_with(structural: int, semantic: int, code: int, lexical: int) -> ChunkHistoryMatch:
    location = StructuralMatch(file_path="legacy/ops.py", chunk_name="f", start_line=1, end_line=5)
    return ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="f", start_line=1, end_line=5),
        structural_matches=[location] * structural,
        semantic_matches=[
            SimilarChunk(file_path="x.py", chunk_name="f", start_line=1, end_line=5, text="t", score=0.9, code="c")
        ]
        * semantic,
        code_matches=[CodeMatch(file_path="y.py", chunk_name="f", start_line=1, end_line=5, code="c", score=0.8)] * code,
        lexical_matches=[LexicalMatch(file_path="z.py", chunk_name="f", start_line=1, end_line=5, code="c", score=3.0)]
        * lexical,
    )


def test_each_kind_of_surviving_candidate_is_counted_under_its_source(metric_reader: InMemoryMetricReader) -> None:
    """Verify the counts follow the buckets of one chunk's match, so the productive search can be named."""
    dry_check._record_candidates(_match_with(structural=1, semantic=2, code=0, lexical=3))

    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "structural"}).value == 1
    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "semantic"}).value == 2
    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "code"}).value == 0
    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "lexical"}).value == 3


def test_counts_add_up_across_chunks(metric_reader: InMemoryMetricReader) -> None:
    """Verify two chunks' candidates accumulate into the same series."""
    dry_check._record_candidates(_match_with(structural=0, semantic=2, code=0, lexical=0))
    dry_check._record_candidates(_match_with(structural=0, semantic=1, code=0, lexical=0))

    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "semantic"}).value == 3
