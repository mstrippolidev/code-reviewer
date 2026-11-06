"""
    Tests that AgentBase reports what a run cost and how it ended. The underlying LangGraph agent is
    faked, as in test_base.py, because this checks our own wiring and not a model's answer.
"""
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from code_reviewer.agents import base
from code_reviewer.agents.base import AgentBase, AgentInvocationError, FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, SizeStatus
from code_reviewer.telemetry.metrics import PipelineMetrics
from code_reviewer.telemetry.run_summary import TokenUsage
from tests.metric_points import AGENT_RUN_DURATION, AGENT_SKIPPED, LLM_TOKENS, point_with, points_for


def _output(code_key: CodeKey) -> AgentOutput:
    return AgentOutput(review=[AgentReviewEntry(code_key=code_key, incidents=[], rating=100)])


def _result_using(input_tokens: int, output_tokens: int) -> dict[str, Any]:
    """What the compiled agent returns: the message history plus the structured answer."""
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return {"messages": [AIMessage(content="", usage_metadata=usage)], "structured_response": _output(CodeKey.VAR)}


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    """Points AgentBase at the private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(base, "pipeline_metrics", isolated_pipeline_metrics)


@pytest.fixture
def agent() -> AgentBase:
    return AgentBase(CodeKey.VAR, "test prompt")


def test_execute_agent_leaves_token_counting_to_the_model_call_observer(
    agent: AgentBase, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the run itself records no tokens, since the observer counts each real call and retries included."""
    agent._agent.invoke = lambda messages, **kwargs: _result_using(120, 30)

    agent.execute_agent("code", "f.py")

    assert points_for(metric_reader, LLM_TOKENS) == []


@pytest.fixture
def exported_spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Points AgentBase's tracer at a private provider so the agent span's attributes can be read back."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(base, "tracer", provider.get_tracer("test"))
    return exporter


def _model_call_using(input_tokens: int) -> dict[str, Any]:
    """What one real model call does inside the agent: report its usage, then hand back the run's result."""
    base.pipeline_metrics.record_llm_usage("VAR", "test-model", TokenUsage(input_tokens=input_tokens))
    return _result_using(input_tokens, 5)


def test_the_agent_span_carries_the_tokens_of_the_calls_made_during_its_run(
    agent: AgentBase, exported_spans: InMemorySpanExporter
) -> None:
    """Verify the totals land on execute_agent, not only on the model-call spans beside it."""
    agent._agent.invoke = lambda messages, **kwargs: _model_call_using(120)

    agent.execute_agent("code", "f.py")

    (span,) = exported_spans.get_finished_spans()
    assert (span.name, span.attributes["code_reviewer.tokens.input"]) == ("execute_agent", 120)


def test_a_batched_run_sums_the_calls_of_every_chunk_on_one_span(
    agent: AgentBase, exported_spans: InMemorySpanExporter
) -> None:
    """Verify one agent run over several chunks reports a single total, so its cost reads as one agent's."""
    agent._agent.batch = lambda payloads, config=None: [_model_call_using(100) for _ in payloads]

    agent.execute_agent_batch(["chunk one", "chunk two"], file_path="f.py")

    (span,) = exported_spans.get_finished_spans()
    assert (span.attributes["code_reviewer.tokens.input"], span.attributes["code_reviewer.llm_calls"]) == (200, 2)


def test_the_usage_log_line_names_the_agent_and_the_file(
    agent: AgentBase, exported_spans: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify one line per agent run says which agent and which file it was."""
    caplog.set_level("INFO", logger="code_reviewer.telemetry.run_usage")
    agent._agent.invoke = lambda messages, **kwargs: _model_call_using(120)

    agent.execute_agent("code", "f.py")

    assert "usage agent=VAR file=f.py input=120" in caplog.text


def test_a_failed_run_still_reports_what_it_spent(agent: AgentBase, exported_spans: InMemorySpanExporter) -> None:
    """Verify an agent that raised after a model call keeps that call's tokens on its span."""

    def spend_then_fail(messages: dict, **kwargs: Any) -> dict:
        _model_call_using(120)
        raise RuntimeError("tool loop limit")

    agent._agent.invoke = spend_then_fail

    with pytest.raises(AgentInvocationError):
        agent.execute_agent("code", "f.py")

    (span,) = exported_spans.get_finished_spans()
    assert span.attributes["code_reviewer.tokens.input"] == 120


def test_execute_agent_records_a_completed_run(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify a normal run lands in the duration histogram as completed."""
    agent._agent.invoke = lambda messages, **kwargs: _result_using(10, 5)

    agent.execute_agent("code", "f.py")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "completed"}).count == 1


def test_execute_agent_records_a_timed_out_run_when_the_model_call_times_out(
    agent: AgentBase, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the hard timeout, which AgentBase re-raises wrapped, still counts as timed_out."""

    def time_out(messages: dict, **kwargs: Any) -> dict:
        raise TimeoutError("LLM call exceeded the hard timeout")

    agent._agent.invoke = time_out

    with pytest.raises(AgentInvocationError):
        agent.execute_agent("code", "f.py")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "timed_out"}).count == 1


def test_execute_agent_records_a_failed_run_for_any_other_error(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify a non-timeout failure is counted as failed."""

    def fail(messages: dict, **kwargs: Any) -> dict:
        raise RuntimeError("provider rejected the request")

    agent._agent.invoke = fail

    with pytest.raises(AgentInvocationError):
        agent.execute_agent("code", "f.py")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "failed"}).count == 1


def test_hard_limit_file_counts_the_agent_as_skipped(metric_reader: InMemoryMetricReader) -> None:
    """Verify a file agent that short-circuits on an oversized file is counted, since it never reaches a model."""
    file_agent = FileSizeAwareAgentBase(CodeKey.COH, "test prompt")

    file_agent.execute_agent("line\n" * 10, "big.py", FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED))

    assert point_with(metric_reader, AGENT_SKIPPED, {"code_reviewer.reason": "file_exceeds_hard_limit"}).value == 1


def test_hard_limit_file_is_not_timed_as_an_agent_run(metric_reader: InMemoryMetricReader) -> None:
    """Verify the short-circuit adds nothing to the duration histogram, which is for runs that did work."""
    file_agent = FileSizeAwareAgentBase(CodeKey.COH, "test prompt")

    file_agent.execute_agent("line\n" * 10, "big.py", FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED))

    assert points_for(metric_reader, AGENT_RUN_DURATION) == []


def test_normal_sized_file_is_not_counted_as_skipped(metric_reader: InMemoryMetricReader) -> None:
    """Verify only the hard-limit path counts as a skip."""
    file_agent = FileSizeAwareAgentBase(CodeKey.COH, "test prompt")
    file_agent._agent.invoke = lambda messages, **kwargs: _result_using(10, 5)

    file_agent.execute_agent("code", "f.py", FileReviewMeta(size_status=SizeStatus.NORMAL))

    assert points_for(metric_reader, AGENT_SKIPPED) == []
