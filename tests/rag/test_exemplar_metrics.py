"""
    Tests that exemplar lookups report how they ended and the best score they saw, before the relevance floor.
    The vector index is a fake, so no embedding call happens here.
"""
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import exemplar_injection, exemplars
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.exemplar_injection import ExemplarCorpora, ExemplarInjection
from code_reviewer.rag.exemplars import ExemplarQuery, ExemplarStore
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.shared_exemplars import SharedExemplarQuery, SharedExemplarStore
from code_reviewer.schemas.review import CodeKey
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import (
    RAG_EXEMPLAR_BEST_SCORE,
    RAG_EXEMPLAR_LOOKUPS,
    RAG_RETRIEVAL_DURATION,
    point_with,
    points_for,
)
from tests.rag.test_exemplar_injection import FakeStore, _capture_prompt, _request

FLOOR = 0.5
_CORPUS = "code_reviewer.corpus"
_CODE_KEY = "code_reviewer.code_key"
_OUTCOME = "code_reviewer.outcome"
_SOURCE = "code_reviewer.source"
REPO_DATA = RepoData(repo_id="r1", commit_sha="abc", owner_id="o1")


class _Node:
    def __init__(self, score: float) -> None:
        self._score = score
        self.node = SimpleNamespace(
            metadata={"code_key": "SOLID1", "file_path": "billing/invoice.py", "chunk_name": "Invoice"},
            get_content=lambda: "class Invoice: ...",
        )

    def get_score(self) -> float:
        return self._score


class _Retriever:
    def __init__(self, scores: list[float], error: Exception | None) -> None:
        self._scores = scores
        self._error = error

    def retrieve(self, code: str) -> list[_Node]:
        if self._error:
            raise self._error
        return [_Node(score) for score in self._scores]


class _Index:
    def __init__(self, scores: list[float], error: Exception | None = None) -> None:
        self._retriever = _Retriever(scores, error)

    def as_retriever(self, similarity_top_k: int, filters: object) -> _Retriever:
        return self._retriever


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the stores and the middleware at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(exemplars, "rag_metrics", isolated_rag_metrics)
    monkeypatch.setattr(exemplar_injection, "rag_metrics", isolated_rag_metrics)


def _repo_store(scores: list[float], error: Exception | None = None) -> ExemplarStore:
    store = ExemplarStore.__new__(ExemplarStore)
    store._index = _Index(scores, error)
    return store


def _shared_store(scores: list[float]) -> SharedExemplarStore:
    store = SharedExemplarStore.__new__(SharedExemplarStore)
    store._index = _Index(scores)
    return store


def _repo_query() -> ExemplarQuery:
    return ExemplarQuery(repo_data=REPO_DATA, code_key=CodeKey.SOLID1, code="class A: ...", relevance_floor=FLOOR)


def test_a_lookup_with_a_candidate_above_the_floor_is_counted_as_injected(metric_reader: InMemoryMetricReader) -> None:
    """Verify a candidate that clears the floor is an injection."""
    _repo_store([0.8, 0.4]).find_exemplars(_repo_query())

    labels = {_CORPUS: "repo", _CODE_KEY: "SOLID1", _OUTCOME: "injected"}
    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, labels).value == 1


def test_a_lookup_with_only_weak_candidates_is_counted_as_below_the_floor(metric_reader: InMemoryMetricReader) -> None:
    """Verify candidates that exist but all miss the floor are told apart from an empty corpus."""
    _repo_store([0.3, 0.45]).find_exemplars(_repo_query())

    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, {_OUTCOME: "below_floor"}).value == 1


def test_a_lookup_that_finds_nothing_is_counted_as_having_no_candidates(metric_reader: InMemoryMetricReader) -> None:
    """Verify an empty result is its own outcome, which is what an empty corpus looks like."""
    _repo_store([]).find_exemplars(_repo_query())

    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, {_OUTCOME: "no_candidates"}).value == 1
    assert points_for(metric_reader, RAG_EXEMPLAR_BEST_SCORE) == []


def test_the_best_score_is_recorded_before_the_floor_removes_it(metric_reader: InMemoryMetricReader) -> None:
    """Verify a score that missed the floor still shows up, so the floor can be judged against real scores."""
    _repo_store([0.3, 0.45]).find_exemplars(_repo_query())

    assert point_with(metric_reader, RAG_EXEMPLAR_BEST_SCORE, {_CORPUS: "repo"}).sum == 0.45


def test_the_shared_corpus_is_labelled_as_shared(metric_reader: InMemoryMetricReader) -> None:
    """Verify the curated repo-less corpus is told apart from a repo's own."""
    query = SharedExemplarQuery(code_key=CodeKey.SOLID1, code="class A: ...", relevance_floor=FLOOR)

    _shared_store([0.9]).find_exemplars(query)

    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, {_CORPUS: "shared", _OUTCOME: "injected"}).value == 1


def test_the_search_itself_is_timed_as_an_exemplar_retrieval(metric_reader: InMemoryMetricReader) -> None:
    """Verify exemplar searches appear in the same retrieval-time metric as DRY's."""
    _repo_store([0.8]).find_exemplars(_repo_query())

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "exemplar"}).count == 1


def test_a_failing_search_still_raises_a_store_query_error(metric_reader: InMemoryMetricReader) -> None:
    """Verify the store keeps raising, and the failed search is timed, with no lookup outcome recorded by the store."""
    store = _repo_store([], error=RuntimeError("store down"))

    with pytest.raises(VectorStoreQueryError):
        store.find_exemplars(_repo_query())

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "exemplar", _OUTCOME: "failed"}).count == 1
    assert points_for(metric_reader, RAG_EXEMPLAR_LOOKUPS) == []


def test_a_store_failure_during_injection_is_counted_as_failed(metric_reader: InMemoryMetricReader) -> None:
    """Verify the failure the middleware swallows to keep the review going is visible as a failed lookup."""
    middleware = ExemplarInjection(CodeKey.SOLID1, ExemplarCorpora(repo=FakeStore(error=RuntimeError("store down"))))

    _capture_prompt(middleware, _request())

    labels = {_CORPUS: "repo", _CODE_KEY: "SOLID1", _OUTCOME: "failed"}
    assert point_with(metric_reader, RAG_EXEMPLAR_LOOKUPS, labels).value == 1
