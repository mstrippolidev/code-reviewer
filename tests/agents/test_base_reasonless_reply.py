"""
    Tests that AgentBase asks again when a reasoning model sends an empty review with no reasoning, that
    this shares one retry with the invented-review check, and that a second bad reply fails the agent.
    The compiled agent is faked: this checks our wiring, not a model.
"""
from dataclasses import replace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.agents import base
from code_reviewer.agents.base import AgentBase, InventedReviewError, ReasonlessReplyError
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import AGENT_INVENTED_REVIEWS, AGENT_REASONLESS_REPLIES, point_with

CODE = "def total(prices):\n    return sum(prices)\n"


def reply(incidents: list[Incident], reasoning: bool) -> dict[str, Any]:
    kwargs = {"reasoning_content": "I read the code."} if reasoning else {}
    entry = AgentReviewEntry(code_key=CodeKey.VAR, incidents=incidents)
    return {
        "messages": [AIMessage(content="answer", additional_kwargs=kwargs)],
        "structured_response": AgentOutput(review=[entry]),
    }


def incident(description: str, line_position: str) -> Incident:
    return Incident(priority=Priority.HIGH, line_position=line_position, description=description, advice="fix")


def real_result() -> dict[str, Any]:
    return reply([incident("`prices` is a vague name.", "1-1")], reasoning=True)


def invented_result() -> dict[str, Any]:
    return reply([incident("`handle_department_created` trusts its payload.", "27-27")], reasoning=True)


def reasonless_empty_result() -> dict[str, Any]:
    return reply([], reasoning=False)


def reasoned_empty_result() -> dict[str, Any]:
    return reply([], reasoning=True)


class ScriptedAgent:
    """Answers each call with the next prepared result and counts the calls."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.calls = 0

    def invoke(self, messages: dict, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return self.results.pop(0)

    def batch(self, payloads: list[dict], config: dict | None = None) -> list[dict[str, Any]]:
        self.calls += 1
        return [self.results.pop(0) for _ in payloads]


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    monkeypatch.setattr(base, "pipeline_metrics", isolated_pipeline_metrics)


@pytest.fixture
def agent() -> AgentBase:
    reasoning_agent = AgentBase(CodeKey.VAR, "test prompt")
    reasoning_agent._reply_rules = replace(reasoning_agent._reply_rules, expects_reasoning=True)
    return reasoning_agent


def test_an_empty_reply_with_no_reasoning_is_asked_again(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify one retry recovers the answer, and that it is counted as retried."""
    scripted = ScriptedAgent([reasonless_empty_result(), real_result()])
    agent._agent = scripted

    output = agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 2
    assert output.review[0].incidents[0].line_position == "1-1"
    assert point_with(metric_reader, AGENT_REASONLESS_REPLIES, {"code_reviewer.result": "retried"}).value == 1


def test_an_empty_reply_that_reasoned_is_not_asked_again(agent: AgentBase) -> None:
    """Verify a clean file the model thought about costs exactly one call."""
    scripted = ScriptedAgent([reasoned_empty_result()])
    agent._agent = scripted

    agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 1


def test_a_model_not_expected_to_reason_is_never_asked_again_for_an_empty_reply() -> None:
    """Verify the default agent, on a provider that sends no reasoning, keeps one call per clean file."""
    plain_agent = AgentBase(CodeKey.VAR, "test prompt")
    scripted = ScriptedAgent([reasonless_empty_result()])
    plain_agent._agent = scripted

    plain_agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 1


def test_two_empty_replies_with_no_reasoning_fail_the_agent(
    agent: AgentBase, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the agent raises instead of reporting a clean file nobody reasoned about, and counts the failure."""
    agent._agent = ScriptedAgent([reasonless_empty_result(), reasonless_empty_result()])

    with pytest.raises(ReasonlessReplyError):
        agent.execute_agent(CODE, "cart.py")

    assert point_with(metric_reader, AGENT_REASONLESS_REPLIES, {"code_reviewer.result": "failed"}).value == 1


def test_an_invented_reply_then_an_empty_one_share_a_single_retry(agent: AgentBase) -> None:
    """Verify the two checks use one retry between them, so the second bad reply fails and no third call is made."""
    scripted = ScriptedAgent([invented_result(), reasonless_empty_result()])
    agent._agent = scripted

    with pytest.raises(ReasonlessReplyError):
        agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 2


def test_an_empty_reply_then_an_invented_one_share_a_single_retry(
    agent: AgentBase, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the retry that an empty reply earned also fails when the second reply is invented."""
    scripted = ScriptedAgent([reasonless_empty_result(), invented_result()])
    agent._agent = scripted

    with pytest.raises(InventedReviewError):
        agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 2
    assert point_with(metric_reader, AGENT_REASONLESS_REPLIES, {"code_reviewer.result": "retried"}).value == 1
    assert point_with(metric_reader, AGENT_INVENTED_REVIEWS, {"code_reviewer.result": "failed"}).value == 1


def test_a_batch_asks_again_only_for_the_chunk_with_the_empty_reply(agent: AgentBase) -> None:
    """Verify the good chunk keeps its answer and only the reasonless chunk is sent a second time."""
    scripted = ScriptedAgent([real_result(), reasonless_empty_result(), real_result()])
    agent._agent = scripted

    outputs = agent.execute_agent_batch([CODE, CODE], file_path="cart.py")

    assert scripted.calls == 2
    assert [output.review[0].incidents[0].line_position for output in outputs] == ["1-1", "1-1"]
