"""
    Tests that RagMetrics turns each RAG event into the right instrument and labels.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.telemetry.rag_metrics import (
    Corpus,
    DuplicateOrigin,
    EmbeddingKind,
    ExemplarOutcome,
    RagMetrics,
    RetrievalSource,
)
from tests.metric_points import (
    RAG_DRY_CANDIDATES,
    RAG_DRY_CHUNKS,
    RAG_DRY_EXACT_MATCHES,
    RAG_EMBEDDING_DURATION,
    RAG_EXEMPLAR_BEST_SCORE,
    RAG_EXEMPLAR_LOOKUPS,
    RAG_EXPLAIN_DURATION,
    RAG_JUDGE_CANDIDATES,
    RAG_JUDGE_DURATION,
    RAG_JUDGE_VERDICTS,
    RAG_RERANK_CANDIDATES_IN,
    RAG_RERANK_CANDIDATES_KEPT,
    RAG_RERANK_DURATION,
    RAG_RETRIEVAL_DURATION,
    point_with,
    points_for,
)

_SOURCE = "code_reviewer.source"
_OUTCOME = "code_reviewer.outcome"
_KIND = "code_reviewer.kind"
_CORPUS = "code_reviewer.corpus"
_CODE_KEY = "code_reviewer.code_key"
_VERDICT = "code_reviewer.verdict"
_ORIGIN = "code_reviewer.origin"


def test_a_search_is_timed_per_source(isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader) -> None:
    """Verify each search source is its own series, so the slow one can be named."""
    with isolated_rag_metrics.track_retrieval(RetrievalSource.SEMANTIC):
        pass
    with isolated_rag_metrics.track_retrieval(RetrievalSource.LEXICAL):
        pass

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "semantic", _OUTCOME: "completed"}).count == 1
    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "lexical", _OUTCOME: "completed"}).count == 1


def test_a_failed_search_is_timed_as_failed_and_still_raises(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a failing search records its time under the failed outcome and the error propagates."""
    with pytest.raises(RuntimeError):
        with isolated_rag_metrics.track_retrieval(RetrievalSource.CODE):
            raise RuntimeError("store down")

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "code", _OUTCOME: "failed"}).count == 1


def test_a_timeout_is_recorded_as_timed_out(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a hard timeout is told apart from an ordinary failure, as it is for agent runs."""
    with pytest.raises(TimeoutError):
        with isolated_rag_metrics.track_explain():
            raise TimeoutError("hard timeout")

    assert point_with(metric_reader, RAG_EXPLAIN_DURATION, {_OUTCOME: "timed_out"}).count == 1


def test_an_embedding_is_timed_per_kind(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify query and document embeddings are separate series."""
    with isolated_rag_metrics.track_embedding(EmbeddingKind.QUERY):
        pass
    with isolated_rag_metrics.track_embedding(EmbeddingKind.DOCUMENT):
        pass

    assert point_with(metric_reader, RAG_EMBEDDING_DURATION, {_KIND: "query"}).count == 1
    assert point_with(metric_reader, RAG_EMBEDDING_DURATION, {_KIND: "document"}).count == 1


def test_a_rerank_and_a_judge_call_are_timed(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify both timers write their own histogram."""
    with isolated_rag_metrics.track_rerank():
        pass
    with isolated_rag_metrics.track_judge():
        pass

    assert points_for(metric_reader, RAG_RERANK_DURATION)[0].count == 1
    assert points_for(metric_reader, RAG_JUDGE_DURATION)[0].count == 1


def test_rerank_candidates_in_and_kept_are_separate_histograms(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify how many candidates went in and how many were kept can each be read on their own."""
    isolated_rag_metrics.record_rerank_candidates(candidates_in=30, candidates_kept=5)

    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_IN)[0].sum == 30
    assert points_for(metric_reader, RAG_RERANK_CANDIDATES_KEPT)[0].sum == 5


def test_an_exemplar_lookup_is_counted_by_corpus_agent_and_outcome(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the injection rate can be read per agent and per corpus."""
    isolated_rag_metrics.record_exemplar_lookup(Corpus.REPO, "SOLID1", ExemplarOutcome.BELOW_FLOOR)

    labels = {_CORPUS: "repo", _CODE_KEY: "SOLID1", _OUTCOME: "below_floor"}
    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, labels).value == 1


def test_the_best_exemplar_score_is_recorded_per_corpus(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the score distribution can be read against the relevance floor, per corpus."""
    isolated_rag_metrics.record_exemplar_best_score(Corpus.SHARED, 0.55)

    point = point_with(metric_reader, RAG_EXEMPLAR_BEST_SCORE, {_CORPUS: "shared"})
    assert (point.count, point.sum) == (1, 0.55)


def test_dry_chunks_are_counted_with_and_without_candidates(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the share of chunks the repo's history can help with is readable."""
    isolated_rag_metrics.record_dry_chunk_with_candidates()
    isolated_rag_metrics.record_dry_chunk_without_candidates()
    isolated_rag_metrics.record_dry_chunk_without_candidates()

    assert point_with(metric_reader, RAG_DRY_CHUNKS, {_OUTCOME: "candidates"}).value == 1
    assert point_with(metric_reader, RAG_DRY_CHUNKS, {_OUTCOME: "no_candidates"}).value == 2


def test_dry_candidates_and_exact_matches_are_counted_by_where_they_came_from(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify candidates are split by search source and exact matches by origin."""
    isolated_rag_metrics.record_dry_candidates(RetrievalSource.LEXICAL, 3)
    isolated_rag_metrics.record_dry_exact_matches(DuplicateOrigin.INTRA_PR, 2)

    assert point_with(metric_reader, RAG_DRY_CANDIDATES, {_SOURCE: "lexical"}).value == 3
    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "intra_pr"}).value == 2


def test_the_judge_call_size_and_verdicts_are_recorded(
    isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the confirm rate can be read from the two verdict series."""
    isolated_rag_metrics.record_judge_call(candidate_count=4)
    isolated_rag_metrics.record_judge_verdicts(duplicates=1, rejected=3)

    assert points_for(metric_reader, RAG_JUDGE_CANDIDATES)[0].sum == 4
    assert point_with(metric_reader, RAG_JUDGE_VERDICTS, {_VERDICT: "duplicate"}).value == 1
    assert point_with(metric_reader, RAG_JUDGE_VERDICTS, {_VERDICT: "not_duplicate"}).value == 3
