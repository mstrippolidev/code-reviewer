"""
    Tests that the DRY judge reports how long a call took, how many candidates it was given and its verdict mix.
    The judge's agent is a fake, so no model is called.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import dry_judge
from code_reviewer.rag.dry_judge import DryJudge, DryJudgeInvocationError, JudgeCandidate
from code_reviewer.schemas.rag.dry_judge import DryJudgeOutput
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_JUDGE_CANDIDATES, RAG_JUDGE_DURATION, RAG_JUDGE_VERDICTS, point_with, points_for
from tests.rag.test_dry_judge_merge import _verdict

_OUTCOME = "code_reviewer.outcome"
_VERDICT = "code_reviewer.verdict"
_CANDIDATES = [JudgeCandidate(location=f"legacy/mod_{index}.py:f (lines 1-5)", code="...") for index in range(3)]


class _FakeAgent:
    def __init__(self, output: DryJudgeOutput | None = None, error: Exception | None = None) -> None:
        self._output = output
        self._error = error

    def invoke(self, messages: dict) -> dict:
        if self._error:
            raise self._error
        return {"structured_response": self._output}


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points the judge at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(dry_judge, "rag_metrics", isolated_rag_metrics)


def _judge(agent: _FakeAgent) -> DryJudge:
    judge = DryJudge.__new__(DryJudge)
    judge._agent = agent
    return judge


def _output(*confirmed: bool) -> DryJudgeOutput:
    return DryJudgeOutput(verdicts=[_verdict(index, is_duplicate=flag) for index, flag in enumerate(confirmed)])


def test_a_call_is_timed_and_its_candidate_count_recorded(metric_reader: InMemoryMetricReader) -> None:
    """Verify one call adds a completed timing and the number of candidates it was asked about."""
    _judge(_FakeAgent(_output(False, False, False))).judge("def f(): ...", _CANDIDATES)

    assert point_with(metric_reader, RAG_JUDGE_DURATION, {_OUTCOME: "completed"}).count == 1
    assert points_for(metric_reader, RAG_JUDGE_CANDIDATES)[0].sum == 3


def test_verdicts_are_split_into_duplicates_and_rejections(metric_reader: InMemoryMetricReader) -> None:
    """Verify the confirm rate can be read from the verdict counters: one of three was confirmed."""
    _judge(_FakeAgent(_output(True, False, False))).judge("def f(): ...", _CANDIDATES)

    assert point_with(metric_reader, RAG_JUDGE_VERDICTS, {_VERDICT: "duplicate"}).value == 1
    assert point_with(metric_reader, RAG_JUDGE_VERDICTS, {_VERDICT: "not_duplicate"}).value == 2


def test_a_failing_call_is_timed_as_failed_and_still_raises_the_same_error(metric_reader: InMemoryMetricReader) -> None:
    """Verify the metric sees the failure and the caller still gets DryJudgeInvocationError, with no verdicts recorded."""
    judge = _judge(_FakeAgent(error=RuntimeError("provider outage")))

    with pytest.raises(DryJudgeInvocationError):
        judge.judge("def f(): ...", _CANDIDATES)

    assert point_with(metric_reader, RAG_JUDGE_DURATION, {_OUTCOME: "failed"}).count == 1
    assert points_for(metric_reader, RAG_JUDGE_VERDICTS) == []


def test_a_timed_out_call_is_recorded_as_timed_out(metric_reader: InMemoryMetricReader) -> None:
    """Verify a hard timeout is told apart from an ordinary failure, since the judge was DRY's long pole."""
    judge = _judge(_FakeAgent(error=TimeoutError("hard timeout")))

    with pytest.raises(DryJudgeInvocationError):
        judge.judge("def f(): ...", _CANDIDATES)

    assert point_with(metric_reader, RAG_JUDGE_DURATION, {_OUTCOME: "timed_out"}).count == 1


def test_a_call_with_no_candidates_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify an empty call never reaches the model and is not counted as a judge call."""
    assert _judge(_FakeAgent()).judge("def f(): ...", []) == []

    assert points_for(metric_reader, RAG_JUDGE_DURATION) == []
    assert points_for(metric_reader, RAG_JUDGE_CANDIDATES) == []
