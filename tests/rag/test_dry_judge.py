"""
    Tests for DryJudge's own judgment quality — content-based checks run
    against a real model, per this project's approach to LLM-backed tests.
    Only fuzzy, un-certain candidates reach the judge at all (an exact
    structural-hash match is templated instead, see rag/dry_review.py), so
    every fixture here is a Type-4 behavioral case, never a hash match.
"""
import pytest

from code_reviewer.rag.dry_judge import DryJudge, JudgeCandidate

LOOP_BASED_SUM = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result"
BUILTIN_BASED_SUM = "def total(values):\n    return sum(values)"
UNRELATED_FUNCTION = "def send_email(to, subject, body):\n    smtp.send(to, subject, body)"
ORDER_TOTAL_WITH_TAX = (
    "def process_order(order):\n"
    "    total = 0\n"
    "    for item in order.items:\n"
    "        total += item.price * item.quantity\n"
    "    apply_tax(total)\n"
    "    return total"
)
ITEM_SUM_ONLY = "def sum_items(items):\n    total = 0\n    for item in items:\n        total += item.price * item.quantity\n    return total"


@pytest.fixture
def dry_judge(small_llm) -> DryJudge:
    return DryJudge(llm=small_llm)


@pytest.mark.llm
def test_behavioral_duplicate_is_confirmed(dry_judge: DryJudge) -> None:
    """Different code, same job — the search only found a topical match;
    confirming it as a real duplicate is the judge's whole reason to exist."""
    candidate = JudgeCandidate(location="legacy/aggregates.py:total (lines 12-16)", code=LOOP_BASED_SUM)

    incidents = dry_judge.judge(BUILTIN_BASED_SUM, [candidate])

    assert incidents != []
    assert incidents[0].priority is not None


@pytest.mark.llm
def test_unrelated_candidate_is_not_confirmed(dry_judge: DryJudge) -> None:
    """A candidate a search surfaced but that does an unrelated job must
    not be reported just because it reached the judge."""
    candidate = JudgeCandidate(location="notifications/mailer.py:send_email (lines 1-2)", code=UNRELATED_FUNCTION)

    incidents = dry_judge.judge(BUILTIN_BASED_SUM, [candidate])

    assert incidents == []


@pytest.mark.llm
def test_partial_duplication_is_confirmed_with_a_narrower_range(dry_judge: DryJudge) -> None:
    """A candidate duplicating only the summing loop inside a larger
    function must be reported against that sub-range, not the whole
    six-line chunk it sits inside."""
    candidate = JudgeCandidate(location="reports/totals.py:sum_items (lines 1-4)", code=ITEM_SUM_ONLY)

    incidents = dry_judge.judge(ORDER_TOTAL_WITH_TAX, [candidate])

    assert incidents != []
    assert incidents[0].line_position != "1-6"


def test_no_candidates_returns_no_incidents_without_a_model_call(dry_judge: DryJudge) -> None:
    assert dry_judge.judge(BUILTIN_BASED_SUM, []) == []


@pytest.mark.llm
def test_confirmed_duplicate_always_carries_a_complete_finding(dry_judge: DryJudge) -> None:
    """DryJudgeVerdict's validator requires every finding field once
    is_duplicate is True, or retry_model corrects the response before it
    ever reaches here — this exercises that against a real model rather
    than a constructed verdict."""
    candidate = JudgeCandidate(location="legacy/aggregates.py:total (lines 12-16)", code=LOOP_BASED_SUM)

    incidents = dry_judge.judge(BUILTIN_BASED_SUM, [candidate])

    assert incidents != []
    incident = incidents[0]
    assert incident.priority is not None
    assert incident.line_position
    assert incident.description
    assert incident.advice
