"""
    Tests that AgentBase asks again when a review is about code it was not given, and fails the agent
    when the second answer is too. The compiled agent is faked: this checks our wiring, not a model.
"""
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.agents import base
from code_reviewer.agents.base import AgentBase, InventedReviewError
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import AGENT_INVENTED_REVIEWS, point_with

CODE = "def total(prices):\n    return sum(prices)\n"


def result_with(description: str, line_position: str) -> dict[str, Any]:
    incident = Incident(priority=Priority.HIGH, line_position=line_position, description=description, advice="fix")
    entry = AgentReviewEntry(code_key=CodeKey.VAR, incidents=[incident])
    return {"messages": [], "structured_response": AgentOutput(review=[entry])}


def real_result() -> dict[str, Any]:
    return result_with("`prices` is a vague name.", "1-1")


def invented_result() -> dict[str, Any]:
    return result_with("`handle_department_created` trusts its payload.", "27-27")


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
    return AgentBase(CodeKey.VAR, "test prompt")


def test_an_invented_answer_is_asked_again_and_the_second_answer_is_used(
    agent: AgentBase, metric_reader: InMemoryMetricReader
) -> None:
    """Verify one retry fixes a glitch, and that it is counted as retried."""
    scripted = ScriptedAgent([invented_result(), real_result()])
    agent._agent = scripted

    output = agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 2
    assert output.review[0].incidents[0].line_position == "1-1"
    assert point_with(metric_reader, AGENT_INVENTED_REVIEWS, {"code_reviewer.result": "retried"}).value == 1


def test_a_real_answer_is_not_asked_again(agent: AgentBase) -> None:
    """Verify a grounded review costs exactly one call."""
    scripted = ScriptedAgent([real_result()])
    agent._agent = scripted

    agent.execute_agent(CODE, "cart.py")

    assert scripted.calls == 1


def test_two_invented_answers_fail_the_agent(agent: AgentBase, metric_reader: InMemoryMetricReader) -> None:
    """Verify the agent raises instead of returning a review about other code, and counts the failure."""
    agent._agent = ScriptedAgent([invented_result(), invented_result()])

    with pytest.raises(InventedReviewError):
        agent.execute_agent(CODE, "cart.py")

    assert point_with(metric_reader, AGENT_INVENTED_REVIEWS, {"code_reviewer.result": "failed"}).value == 1


def test_a_batch_asks_again_only_for_the_chunk_that_was_invented(agent: AgentBase) -> None:
    """Verify the good chunk keeps its answer and only the invented one is sent a second time."""
    scripted = ScriptedAgent([real_result(), invented_result(), real_result()])
    agent._agent = scripted

    outputs = agent.execute_agent_batch([CODE, CODE], file_path="cart.py")

    assert scripted.calls == 2
    assert [output.review[0].incidents[0].line_position for output in outputs] == ["1-1", "1-1"]
