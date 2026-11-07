"""
    Tests for the exemplar judge and jury against fakes: how one model's verdicts become a list of
    candidates, and how several judges' lists become a unanimous one. No model call happens here.
"""
import threading

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.prompts.rag.exemplar_judge import PRINCIPLE_FOCUS
from code_reviewer.rag import exemplar_judge
from code_reviewer.rag.errors import ExemplarJudgeInvocationError
from code_reviewer.rag.exemplar_judge import ExemplarJudge, ExemplarJury
from code_reviewer.rag.exemplars import Exemplar
from code_reviewer.schemas.rag.exemplar_judge import ExemplarJudgeOutput, ExemplarRelevance, ExemplarVerdict
from code_reviewer.schemas.review import CodeKey
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_EXEMPLAR_JURY_CANDIDATES, point_with

_RESULT = "code_reviewer.result"
CODE_UNDER_REVIEW = "class Billing:\n    def pay(self): ..."


def _candidate(name: str) -> Exemplar:
    return Exemplar(code_key=CodeKey.SOLID1, file_path=f"good/{name}.py", chunk_name=name, code=f"class {name}: ...", score=0.5)


FIRST, SECOND, THIRD = _candidate("First"), _candidate("Second"), _candidate("Third")
CANDIDATES = [FIRST, SECOND, THIRD]


class _FakeAgent:
    """Answers with fixed verdicts, or fails, and keeps the prompt it was sent."""

    def __init__(self, verdicts: list[ExemplarVerdict] | None = None, error: Exception | None = None) -> None:
        self._verdicts = verdicts or []
        self._error = error
        self.prompt: str | None = None

    def invoke(self, messages: dict) -> dict:
        self.prompt = messages["messages"][0]["content"]
        if self._error:
            raise self._error
        return {"structured_response": ExemplarJudgeOutput(verdicts=self._verdicts)}


def _verdict(position: int, relevant: bool) -> ExemplarVerdict:
    status = ExemplarRelevance.RELEVANT if relevant else ExemplarRelevance.NOT_RELEVANT
    return ExemplarVerdict(candidate_index=position, status=status)


def _judge_with(agent: _FakeAgent) -> ExemplarJudge:
    judge = ExemplarJudge.__new__(ExemplarJudge)
    judge._agent = agent
    return judge


class _FakeJudge:
    """Stands in for one jury member, answering a fixed list of candidates."""

    def __init__(self, relevant: list[Exemplar], error: Exception | None = None) -> None:
        self._relevant = relevant
        self._error = error

    def pick_relevant(self, code_key: CodeKey, code: str, candidates: list[Exemplar]) -> list[Exemplar]:
        if self._error:
            raise self._error
        return self._relevant


def test_a_judge_returns_the_candidates_it_marked_relevant_in_the_order_given() -> None:
    """Verify verdicts are mapped back to the right candidates, whatever order the model listed them in."""
    agent = _FakeAgent([_verdict(2, True), _verdict(1, False), _verdict(0, True)])

    picked = _judge_with(agent).pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)

    assert picked == [FIRST, THIRD]


def test_a_candidate_the_judge_skips_counts_as_not_relevant() -> None:
    """Verify silence is never read as approval, since a wrong exemplar is worse than none."""
    agent = _FakeAgent([_verdict(0, True)])

    picked = _judge_with(agent).pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)

    assert picked == [FIRST]


def test_a_verdict_for_a_candidate_that_does_not_exist_is_ignored() -> None:
    """Verify an out-of-range index from the model cannot select anything."""
    agent = _FakeAgent([_verdict(0, False), _verdict(7, True)])

    assert _judge_with(agent).pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES) == []


def test_a_failing_model_call_is_raised_as_a_judge_error() -> None:
    """Verify the caller learns the judge could not answer instead of reading an empty list as 'none relevant'."""
    judge = _judge_with(_FakeAgent(error=RuntimeError("provider down")))

    with pytest.raises(ExemplarJudgeInvocationError):
        judge.pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)


def test_the_prompt_carries_the_code_under_review_the_principle_and_every_candidate() -> None:
    """Verify the judge sees everything the verdict depends on."""
    agent = _FakeAgent([_verdict(0, True)])

    _judge_with(agent).pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)

    expected = [CODE_UNDER_REVIEW, PRINCIPLE_FOCUS[CodeKey.SOLID1], *(candidate.code for candidate in CANDIDATES)]
    assert all(part in agent.prompt for part in expected)


def test_a_candidate_survives_only_when_every_judge_marks_it_relevant() -> None:
    """Verify unanimity: a candidate two judges like and one dislikes is left out."""
    jury = ExemplarJury(
        [_FakeJudge([FIRST, SECOND]), _FakeJudge([FIRST, SECOND, THIRD]), _FakeJudge([FIRST, THIRD])]
    )

    assert jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES) == [FIRST]


def test_the_confirmed_candidates_keep_the_order_they_were_given_in() -> None:
    """Verify the most similar candidate stays first, so the top ones are the ones injected."""
    jury = ExemplarJury([_FakeJudge([THIRD, FIRST]), _FakeJudge([FIRST, THIRD])])

    assert jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES) == [FIRST, THIRD]


def test_no_candidates_means_no_judge_is_asked() -> None:
    """Verify an empty corpus costs no model call."""
    jury = ExemplarJury([_FakeJudge([], error=RuntimeError("must not be called"))])

    assert jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, []) == []


def test_one_failing_judge_fails_the_whole_vote() -> None:
    """Verify a missing vote is not mistaken for a 'no', which would hide an outage as a rejection."""
    jury = ExemplarJury([_FakeJudge([FIRST]), _FakeJudge([], error=ExemplarJudgeInvocationError("down"))])

    with pytest.raises(ExemplarJudgeInvocationError):
        jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)


def test_the_judges_are_asked_at_the_same_time() -> None:
    """Verify the lookup waits for the slowest judge, not for all of them in turn: each fake blocks until every
    judge has arrived, which can only happen when they run concurrently."""
    barrier = threading.Barrier(3)

    class _WaitingJudge:
        def pick_relevant(self, code_key: CodeKey, code: str, candidates: list[Exemplar]) -> list[Exemplar]:
            barrier.wait(timeout=5)
            return candidates

    jury = ExemplarJury([_WaitingJudge(), _WaitingJudge(), _WaitingJudge()])

    assert jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES) == CANDIDATES


def test_each_candidates_vote_is_counted_by_whether_the_judges_agreed(
    monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the jury reports one result per candidate, so the split rate can be read."""
    monkeypatch.setattr(exemplar_judge, "rag_metrics", isolated_rag_metrics)
    jury = ExemplarJury([_FakeJudge([FIRST, SECOND]), _FakeJudge([FIRST, SECOND]), _FakeJudge([FIRST])])

    jury.confirm(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)

    assert point_with(metric_reader, RAG_EXEMPLAR_JURY_CANDIDATES, {_RESULT: "unanimous_relevant"}).value == 1
    assert point_with(metric_reader, RAG_EXEMPLAR_JURY_CANDIDATES, {_RESULT: "split"}).value == 1
    assert point_with(metric_reader, RAG_EXEMPLAR_JURY_CANDIDATES, {_RESULT: "unanimous_not_relevant"}).value == 1
