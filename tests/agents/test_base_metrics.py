"""
    Tests that AgentBase reports what a run cost and how it ended. The underlying LangGraph agent is
    faked, as in test_base.py, because this checks our own wiring and not a model's answer.
"""
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.agents import base
from code_reviewer.agents.base import AgentBase, AgentInvocationError, FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, SizeStatus
from code_reviewer.telemetry.metrics import PipelineMetrics
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


def test_execute_agent_reports_the_input_tokens_of_the_run(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify the usage found in the run's messages is reported under the agent's code_key."""
    agent._agent.invoke = lambda messages, **kwargs: _result_using(120, 30)

    agent.execute_agent("code", "f.py")

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.code_key": "VAR", "code_reviewer.token_type": "input"}).value == 120


def test_execute_agent_labels_tokens_with_the_agents_own_model(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify the model label is the model this agent was built with."""
    agent._agent.invoke = lambda messages, **kwargs: _result_using(120, 30)

    agent.execute_agent("code", "f.py")

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.model": agent._model_name}).value == 120


def test_execute_agent_batch_adds_up_the_tokens_of_every_chunk(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify a batched run reports each chunk's usage, not just the first."""
    agent._agent.batch = lambda payloads, config=None: [_result_using(100, 10) for _ in payloads]

    agent.execute_agent_batch(["chunk one", "chunk two"], file_path="f.py")

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": "input"}).value == 200


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
