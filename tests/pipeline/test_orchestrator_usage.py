"""
    A review's span carries the sum of what its files spent, and each file's span the sum of its agents'.
    The agents are fakes that report a fixed usage per call, so the numbers are known in advance.
"""
from dataclasses import replace

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline import orchestrator
from code_reviewer.pipeline.orchestrator import run_pipeline
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.schemas.review import AgentOutput, CodeKey, SizeStatus
from code_reviewer.schemas.submission import SubmittedFile
from code_reviewer.telemetry.metrics import PipelineMetrics, pipeline_metrics
from code_reviewer.telemetry.run_summary import TokenUsage
from code_reviewer.telemetry.run_usage import add_cost_to_current_run
from tests.metric_points import REVIEW_COST, points_for
from tests.pipeline.test_orchestrator import (
    FakeAgent,
    FakeCodeSimilarityIndex,
    FakeDryJudge,
    FakeEmbeddingIndex,
    FakeRerankPostprocessor,
)

INPUT = "code_reviewer.tokens.input"
CALLS = "code_reviewer.llm_calls"
TOKENS_PER_CALL = 100
COST_PER_CALL = 0.5


class SpendingAgent(FakeAgent):
    """Reports one model call of a fixed size every time it reviews something."""

    def execute_agent(
        self, code: str, file_path: str | None = None, size_status: SizeStatus | None = None
    ) -> AgentOutput:
        pipeline_metrics.record_llm_usage(self._code_key.value, "test-model", TokenUsage(input_tokens=TOKENS_PER_CALL))
        return super().execute_agent(code, file_path, size_status)


class PricedAgent(SpendingAgent):
    """Also reports a cost for its call, the way api's cost listener does for a priced model."""

    def execute_agent(
        self, code: str, file_path: str | None = None, size_status: SizeStatus | None = None
    ) -> AgentOutput:
        add_cost_to_current_run(COST_PER_CALL)
        return super().execute_agent(code, file_path, size_status)


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(orchestrator, "tracer", provider.get_tracer("test"))
    return exporter


@pytest.fixture(autouse=True)
def skip_intake_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "run_intake_screen", lambda content, llm=None: None)


@pytest.fixture
def container() -> AgentsContainer:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    return AgentsContainer(
        file_agents=[SpendingAgent(CodeKey.COH)],
        chunk_agents=[],
        tcase_agent=SpendingAgent(CodeKey.TCASE),
        dry_judge=FakeDryJudge(),
        rag_manager=FakeEmbeddingIndex(),
        structural_hash_store=StructuralHashStore(engine=engine, schema_name=None),
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=100, postprocessor=FakeRerankPostprocessor()),
    )


def _spans(exporter: InMemorySpanExporter, name: str) -> list[ReadableSpan]:
    return [span for span in exporter.get_finished_spans() if span.name == name]


@pytest.fixture
def priced_container(container: AgentsContainer) -> AgentsContainer:
    return replace(container, file_agents=[PricedAgent(CodeKey.COH)], tcase_agent=PricedAgent(CodeKey.TCASE))


@pytest.fixture
def review_cost_metrics(monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics) -> PipelineMetrics:
    monkeypatch.setattr(orchestrator, "pipeline_metrics", isolated_pipeline_metrics)
    return isolated_pipeline_metrics


@pytest.mark.asyncio
async def test_a_review_reports_its_total_cost_once(
    priced_container: AgentsContainer, review_cost_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify one review is one point in the review-cost histogram, holding the sum over every file."""
    files = [SubmittedFile(file_path=path, content="x = 1\n") for path in ("a.py", "b.py")]

    await run_pipeline(files, priced_container)

    point = points_for(metric_reader, REVIEW_COST)[0]
    assert (point.count, point.sum) == (1, 4 * COST_PER_CALL)


@pytest.mark.asyncio
async def test_a_review_that_fails_before_its_report_reports_no_cost(
    priced_container: AgentsContainer,
    review_cost_metrics: PipelineMetrics,
    metric_reader: InMemoryMetricReader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify an unfinished review does not enter the cost distribution."""

    class FailingAggregator:
        def build_output(self, *args: object) -> None:
            raise RuntimeError("aggregation failed")

    monkeypatch.setattr(orchestrator, "Aggregator", FailingAggregator)

    with pytest.raises(RuntimeError):
        await run_pipeline([SubmittedFile(file_path="a.py", content="x = 1\n")], priced_container)

    assert points_for(metric_reader, REVIEW_COST) == []


@pytest.mark.asyncio
async def test_a_files_span_carries_what_its_agents_spent(container: AgentsContainer, exporter: InMemorySpanExporter) -> None:
    """Verify COH and TCASE, one call each, make 200 input tokens on the file's span."""
    await run_pipeline([SubmittedFile(file_path="a.py", content="x = 1\n")], container)

    (file_span,) = _spans(exporter, "review_file")
    assert (file_span.attributes[INPUT], file_span.attributes[CALLS]) == (2 * TOKENS_PER_CALL, 2)


@pytest.mark.asyncio
async def test_a_review_is_the_sum_of_its_files(
    container: AgentsContainer, exporter: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the review's total equals the files' totals added together, so nothing is lost on the way up.

    The review's own span comes from a decorator bound at import, so its total is read from the log line the
    same block writes.
    """
    caplog.set_level("INFO", logger="code_reviewer.telemetry.run_usage")
    files = [SubmittedFile(file_path=path, content="x = 1\n") for path in ("a.py", "b.py")]

    await run_pipeline(files, container)

    file_total = sum(span.attributes[INPUT] for span in _spans(exporter, "review_file"))
    assert file_total == 4 * TOKENS_PER_CALL
    assert f"usage review input={file_total}" in caplog.text
