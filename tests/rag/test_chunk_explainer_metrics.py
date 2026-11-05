"""
    Tests that the chunk explainer times its LLM call. The agent is a fake, so no model is called.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import chunk_explainer as chunk_explainer_module
from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.errors import ChunkExplanationError
from code_reviewer.schemas.chunk_explanation import ChunkExplanation
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_EXPLAIN_DURATION, point_with
from tests.rag.test_chunk_explainer import ADD_FUNCTION, _FakeLLMInterface

_OUTCOME = "code_reviewer.outcome"


class _FakeAgent:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def invoke(self, messages: dict) -> dict:
        if self._error:
            raise self._error
        return {"structured_response": ChunkExplanation(explanation="Adds two numbers.")}


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the explainer at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(chunk_explainer_module, "rag_metrics", isolated_rag_metrics)


def _explainer(monkeypatch: pytest.MonkeyPatch, agent: _FakeAgent) -> ChunkExplainer:
    monkeypatch.setattr(chunk_explainer_module, "create_agent", lambda **kwargs: agent)
    return ChunkExplainer(llm=_FakeLLMInterface())


def test_an_explanation_is_timed(monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader) -> None:
    """Verify one explain call adds one completed timing."""
    _explainer(monkeypatch, _FakeAgent()).explain(ADD_FUNCTION)

    assert point_with(metric_reader, RAG_EXPLAIN_DURATION, {_OUTCOME: "completed"}).count == 1


def test_a_failed_explanation_is_timed_as_failed_and_still_raises(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the metric sees the failure and the caller still gets ChunkExplanationError."""
    explainer = _explainer(monkeypatch, _FakeAgent(RuntimeError("boom")))

    with pytest.raises(ChunkExplanationError):
        explainer.explain(ADD_FUNCTION)

    assert point_with(metric_reader, RAG_EXPLAIN_DURATION, {_OUTCOME: "failed"}).count == 1


def test_a_timed_out_explanation_is_recorded_as_timed_out(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the hard timeout the OpenRouter-contention note describes shows up as its own outcome."""
    explainer = _explainer(monkeypatch, _FakeAgent(TimeoutError("hard timeout")))

    with pytest.raises(ChunkExplanationError):
        explainer.explain(ADD_FUNCTION)

    assert point_with(metric_reader, RAG_EXPLAIN_DURATION, {_OUTCOME: "timed_out"}).count == 1
