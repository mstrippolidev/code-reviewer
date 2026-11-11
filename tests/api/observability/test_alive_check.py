"""
    Tests that AliveCheck probes each distinct model tier and records the result without ever raising.
"""
import asyncio

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.observability.alive_check import AliveCheck
from api.observability.metrics import ApiMetrics
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey
from tests.metric_points import ALIVE_CHECK_RUNS, point_with, points_for

_TIER = "code_reviewer.tier"
_RESULT = "code_reviewer.result"
_MODEL = "code_reviewer.model"


class FakeLLM:
    def __init__(self, model_name: str, fast: "FakeLLM | None" = None) -> None:
        self.model_name = model_name
        self._fast = fast

    def for_fast_tier(self) -> "FakeLLM":
        return self._fast or self


class FakeOutput:
    def __init__(self, failed: bool) -> None:
        self.review = [AgentReviewEntry(code_key=CodeKey.VAR, incidents=[], rating=100, failed=failed)]


class FakeAgent:
    def __init__(self, failed: bool = False, error: Exception | None = None) -> None:
        self._failed = failed
        self._error = error

    def execute_agent(self, code: str, file_path: str) -> FakeOutput:
        if self._error is not None:
            raise self._error
        return FakeOutput(self._failed)


def _alive_check(
    llm: FakeLLM, metrics: ApiMetrics, monkeypatch: pytest.MonkeyPatch, agent: FakeAgent, seconds: int = 60
) -> AliveCheck:
    check = AliveCheck(llm, metrics, seconds)  # type: ignore[arg-type]
    monkeypatch.setattr(check, "_build_agent", lambda tier_llm: agent)
    return check


def test_one_model_for_both_tiers_is_probed_once(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a deployment whose fast tier is the main model makes a single call."""
    check = _alive_check(FakeLLM("model-a"), isolated_api_metrics, monkeypatch, FakeAgent())

    asyncio.run(check.run_once())

    assert len(points_for(metric_reader, ALIVE_CHECK_RUNS)) == 1
    assert point_with(metric_reader, ALIVE_CHECK_RUNS, {_TIER: "main", _MODEL: "model-a", _RESULT: "ok"}).value == 1


def test_two_different_models_are_probed_separately(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a distinct fast model gets its own call and its own series."""
    llm = FakeLLM("model-a", fast=FakeLLM("model-b"))
    check = _alive_check(llm, isolated_api_metrics, monkeypatch, FakeAgent())

    asyncio.run(check.run_once())

    assert point_with(metric_reader, ALIVE_CHECK_RUNS, {_TIER: "fast", _MODEL: "model-b", _RESULT: "ok"}).value == 1
    assert len(points_for(metric_reader, ALIVE_CHECK_RUNS)) == 2


def test_a_raising_agent_is_counted_failed_and_does_not_raise(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a provider error is recorded and never reaches the API."""
    check = _alive_check(FakeLLM("model-a"), isolated_api_metrics, monkeypatch, FakeAgent(error=TimeoutError()))

    asyncio.run(check.run_once())

    assert point_with(metric_reader, ALIVE_CHECK_RUNS, {_TIER: "main", _MODEL: "model-a", _RESULT: "failed"}).value == 1


def test_a_failed_entry_is_counted_failed(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a reply that came back flagged failed does not count as alive."""
    check = _alive_check(FakeLLM("model-a"), isolated_api_metrics, monkeypatch, FakeAgent(failed=True))

    asyncio.run(check.run_once())

    assert point_with(metric_reader, ALIVE_CHECK_RUNS, {_TIER: "main", _MODEL: "model-a", _RESULT: "failed"}).value == 1


def test_nothing_is_probed_before_the_first_interval(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify starting the loop makes no call, and stopping it ends the task cleanly."""
    check = _alive_check(FakeLLM("model-a"), isolated_api_metrics, monkeypatch, FakeAgent(), seconds=3600)

    async def start_and_stop() -> None:
        check.start()
        await asyncio.sleep(0.05)
        await check.stop()

    asyncio.run(start_and_stop())

    assert points_for(metric_reader, ALIVE_CHECK_RUNS) == []
