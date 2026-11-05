"""
    Tests that every embedding the system performs is timed: the mixin times each hook, and every provider
    builds its client from it.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag.embedding import timed
from code_reviewer.rag.embedding.bedrock import TimedBedrockEmbedding
from code_reviewer.rag.embedding.ollama import OllamaEmbeddingProvider, TimedOllamaEmbedding
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.embedding.timed import TimedEmbeddingMixin
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_EMBEDDING_DURATION, point_with

_KIND = "code_reviewer.kind"
_OUTCOME = "code_reviewer.outcome"


class _FakeEmbedding:
    def _get_query_embedding(self, query: str) -> list[float]:
        return [1.0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return [2.0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [[3.0] for _ in texts]


class _FailingEmbedding(_FakeEmbedding):
    def _get_query_embedding(self, query: str) -> list[float]:
        raise ConnectionError("ollama is down")


class _TimedFake(TimedEmbeddingMixin, _FakeEmbedding):
    pass


class _TimedFailing(TimedEmbeddingMixin, _FailingEmbedding):
    pass


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the mixin at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(timed, "rag_metrics", isolated_rag_metrics)


def test_a_query_embedding_is_timed_and_returned_unchanged(metric_reader: InMemoryMetricReader) -> None:
    """Verify the wrapped hook's result passes through, and the call is counted as a query embedding."""
    assert _TimedFake()._get_query_embedding("def f(): ...") == [1.0]

    assert point_with(metric_reader, RAG_EMBEDDING_DURATION, {_KIND: "query", _OUTCOME: "completed"}).count == 1


def test_a_single_document_and_a_batch_are_each_timed_as_document_embeddings(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify indexing-time embedding, single or batched, is its own series next to query-time embedding."""
    model = _TimedFake()

    assert model._get_text_embedding("code") == [2.0]
    assert model._get_text_embeddings(["a", "b"]) == [[3.0], [3.0]]

    assert point_with(metric_reader, RAG_EMBEDDING_DURATION, {_KIND: "document"}).count == 2


def test_a_failing_embedding_is_timed_as_failed_and_still_raises(metric_reader: InMemoryMetricReader) -> None:
    """Verify an embedding outage is visible in the metric and still propagates to fail the work as before."""
    with pytest.raises(ConnectionError):
        _TimedFailing()._get_query_embedding("def f(): ...")

    assert point_with(metric_reader, RAG_EMBEDDING_DURATION, {_KIND: "query", _OUTCOME: "failed"}).count == 1


def test_the_ollama_text_provider_builds_a_timed_client() -> None:
    """Verify the provider every text embedding goes through hands out a client that is timed."""
    assert isinstance(OllamaEmbeddingProvider().create_embedding_model(), TimedOllamaEmbedding)


def test_the_ollama_code_provider_builds_a_timed_client() -> None:
    """Verify the code-embedding provider is timed too, since DRY's raw-code search depends on it."""
    assert isinstance(OllamaCodeEmbeddingProvider().create_embedding_model(), TimedOllamaEmbedding)


def test_the_bedrock_client_is_timed() -> None:
    """Verify the hosted provider's client class carries the mixin, without building a real AWS client."""
    assert issubclass(TimedBedrockEmbedding, TimedEmbeddingMixin)
