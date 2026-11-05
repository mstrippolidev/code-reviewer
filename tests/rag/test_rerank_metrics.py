"""
    Tests that the re-ranker reports how long it took, how many candidates it kept, and a failure it recovers from.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import rerank
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import (
    RAG_RERANK_CANDIDATES_IN,
    RAG_RERANK_CANDIDATES_KEPT,
    RAG_RERANK_DURATION,
    point_with,
    points_for,
)
from tests.rag.test_rerank import QUERY_CODE, _FakePostprocessor, _match, _semantic_match

_OUTCOME = "code_reviewer.outcome"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the re-ranker at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(rerank, "rag_metrics", isolated_rag_metrics)


def _three_candidates():
    return _match(semantic_matches=[_semantic_match(file_path=f"legacy/{name}.py") for name in ("a", "b", "c")])


def test_a_rerank_pass_is_timed(metric_reader: InMemoryMetricReader) -> None:
    """Verify one pass adds one completed timing."""
    HistoryMatchReranker(max_candidates=2, postprocessor=_FakePostprocessor()).rerank(QUERY_CODE, _three_candidates())

    assert point_with(metric_reader, RAG_RERANK_DURATION, {_OUTCOME: "completed"}).count == 1


def test_candidates_in_and_kept_are_recorded(metric_reader: InMemoryMetricReader) -> None:
    """Verify the pass reports how hard it pruned: three went in, the cap kept two."""
    HistoryMatchReranker(max_candidates=2, postprocessor=_FakePostprocessor()).rerank(QUERY_CODE, _three_candidates())

    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_IN)[0].sum == 3
    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_KEPT)[0].sum == 2


def test_a_chunk_with_no_similarity_candidates_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify a chunk whose only evidence is structural never reaches the cross-encoder, so there is nothing to time."""
    HistoryMatchReranker(max_candidates=2, postprocessor=_FakePostprocessor()).rerank(QUERY_CODE, _match())

    assert points_for(metric_reader, RAG_RERANK_DURATION) == []
    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_IN) == []


def test_a_failing_cross_encoder_is_timed_as_failed_and_keeps_the_candidates(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the failure DRY recovers from is visible in the metric, and the unranked candidates still come through."""
    match = _three_candidates()
    reranker = HistoryMatchReranker(max_candidates=2, postprocessor=_FakePostprocessor(error=True))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert point_with(metric_reader, RAG_RERANK_DURATION, {_OUTCOME: "failed"}).count == 1
    assert len(reranked.semantic_matches) == 3
    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_KEPT) == []
