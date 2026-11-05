"""
    Tests that DRY's history search times each of its four sources and counts the chunks that found nothing.
    The stores are fakes, so these measure only the reporting around the searches.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from sqlalchemy import Engine, create_engine

from code_reviewer.rag import dry_matching
from code_reviewer.rag.dry_matching import CrossHistoryDuplicateFinder, DuplicateEvidenceSources
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_DRY_CHUNKS, RAG_RETRIEVAL_DURATION, point_with, points_for
from tests.rag.test_dry_matching import ADD_FUNCTION, _FakeCodeSimilarityIndex, _FakeEmbeddingIndex

_SOURCE = "code_reviewer.source"
_OUTCOME = "code_reviewer.outcome"
REPO_DATA = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")


class _FailingEmbeddingIndex(_FakeEmbeddingIndex):
    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        raise RuntimeError("explain failed")


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the finder at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(dry_matching, "rag_metrics", isolated_rag_metrics)


@pytest.fixture
def sqlite_engine() -> Engine:
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def structural_hash_store(sqlite_engine: Engine) -> StructuralHashStore:
    return StructuralHashStore(engine=sqlite_engine, schema_name=None)


def _finder(store: StructuralHashStore, embedding_index: _FakeEmbeddingIndex | None = None) -> CrossHistoryDuplicateFinder:
    sources = DuplicateEvidenceSources(
        structural_hash_store=store,
        embedding_index=embedding_index or _FakeEmbeddingIndex(),
        code_similarity_index=_FakeCodeSimilarityIndex(),
    )
    return CrossHistoryDuplicateFinder(sources, REPO_DATA)


def test_each_of_the_four_searches_is_timed_once_per_chunk(
    structural_hash_store: StructuralHashStore, metric_reader: InMemoryMetricReader
) -> None:
    """Verify one chunk adds one timed search for each source, so the slow one can be named."""
    _finder(structural_hash_store).find("a.py", ADD_FUNCTION)

    for source in ("structural", "semantic", "code", "lexical"):
        assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: source, _OUTCOME: "completed"}).count == 1


def test_a_chunk_with_nothing_in_the_history_is_counted_without_candidates(
    structural_hash_store: StructuralHashStore, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a chunk no search found anything for is counted, which is what a sparse corpus looks like."""
    _finder(structural_hash_store).find("a.py", ADD_FUNCTION)

    assert point_with(metric_reader, RAG_DRY_CHUNKS, {_OUTCOME: "no_candidates"}).value == 1
    assert points_for(metric_reader, RAG_DRY_CHUNKS)[0].value == 1


def test_a_chunk_with_a_candidate_is_counted_with_candidates(
    structural_hash_store: StructuralHashStore, metric_reader: InMemoryMetricReader
) -> None:
    """Verify one search finding something is enough for the chunk to count as having candidates."""
    candidate = SimilarChunk(
        file_path="legacy/ops.py", chunk_name="plus", start_line=1, end_line=2, text="adds", score=0.9, code=ADD_FUNCTION
    )

    _finder(structural_hash_store, _FakeEmbeddingIndex([candidate])).find("a.py", ADD_FUNCTION)

    assert point_with(metric_reader, RAG_DRY_CHUNKS, {_OUTCOME: "candidates"}).value == 1


def test_a_failing_search_is_timed_as_failed_and_still_raises(
    structural_hash_store: StructuralHashStore, metric_reader: InMemoryMetricReader
) -> None:
    """Verify an error in one search is visible in the metric and still propagates to fail the run as before."""
    finder = _finder(structural_hash_store, _FailingEmbeddingIndex())

    with pytest.raises(RuntimeError):
        finder.find("a.py", ADD_FUNCTION)

    assert point_with(metric_reader, RAG_RETRIEVAL_DURATION, {_SOURCE: "semantic", _OUTCOME: "failed"}).count == 1
