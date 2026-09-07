"""
    Tests for DryJudge's own judgment quality — content-based checks run
    against a real model, per this project's approach to LLM-backed tests.
    Only fuzzy, un-certain candidates reach the judge at all (an exact
    structural-hash match is templated instead, see rag/dry_review.py), so
    every fixture here is a Type-4 behavioral case, never a hash match.
"""
import pytest

from code_reviewer.rag.dry_judge import DryJudge, JudgeCandidate
from code_reviewer.schemas.review import Priority

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

# A wrapper function nesting a 6-line duplicatable block, used to sweep how
# much of that block a candidate has to share before it's a real duplicate
# rather than a superficial lookalike.
QUERY_WITH_EMBEDDED_TOTAL = (
    "def process_order(order):\n"
    "    def total(values):\n"
    "        if not values:\n"
    "            return 0\n"
    "        result = 0\n"
    "        for value in values:\n"
    "            result += value\n"
    "        return result\n"
    "    grand_total = total(order.item_prices)\n"
    "    apply_discount(order, grand_total)\n"
    "    return grand_total\n"
)
_GUARD_CLAUSE_ONLY = "def guard_check(values):\n    if not values:\n        return 0\n    return len(values)\n"
_GUARD_AND_INIT = "def guard_and_init(values):\n    if not values:\n        return 0\n    result = 0\n    return result\n"
_GUARD_INIT_AND_EMPTY_LOOP = (
    "def guard_init_and_loop_start(values):\n"
    "    if not values:\n"
    "        return 0\n"
    "    result = 0\n"
    "    for value in values:\n"
    "        pass\n"
    "    return result\n"
)
_SAME_SHAPE_WRONG_RESULT = (
    "def sum_values_doubled(values):\n"
    "    if not values:\n"
    "        return 0\n"
    "    result = 0\n"
    "    for value in values:\n"
    "        result += value\n"
    "    return result * 2\n"
)
_COMPLETE_MATCH = (
    "def sum_values(values):\n"
    "    if not values:\n"
    "        return 0\n"
    "    result = 0\n"
    "    for value in values:\n"
    "        result += value\n"
    "    return result\n"
)

_PAYMENT_QUERY = (
    "def charge_customer(order):\n"
    "    fee = order.amount * 0.029 + 0.30\n"
    "    total = order.amount + fee\n"
    "    stripe_client.charge(order.customer_id, total)\n"
    "    return total\n"
)
_PAYMENT_FEE_DUPLICATE = (
    "def compute_refund_fee(order):\n"
    "    processing_fee = (order.amount * 0.029) + 0.30\n"
    "    net = order.amount + processing_fee\n"
    "    return net\n"
)

_MULTI_REGION_QUERY = (
    "def process_order(order):\n"
    "    def total(values):\n"
    "        result = 0\n"
    "        for value in values:\n"
    "            result += value\n"
    "        return result\n"
    "    grand_total = total(order.item_prices)\n"
    "    def slug(text):\n"
    "        return text.lower().replace(' ', '-')\n"
    "    order_slug = slug(order.name)\n"
    "    return grand_total, order_slug\n"
)
_SUM_CANDIDATE_CODE = "def sum_all(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"
_SLUG_CANDIDATE_CODE = "def slugify(text):\n    return text.lower().replace(' ', '-')\n"

# Behaviorally identical (both validate a 0-100 range) via a different AST
# shape (comparison chain vs. branching), so it reaches the judge rather
# than being templated by the structural-hash bucket — but the two
# functions serve conceptually unrelated purposes with no shared name.
_INDEPENDENT_DOMAIN_QUERY = "def is_valid_order_quantity(n):\n    return 0 <= n <= 100\n"
_INDEPENDENT_DOMAIN_CANDIDATE = (
    "def is_valid_score(n):\n    if n < 0 or n > 100:\n        return False\n    return True\n"
)


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


@pytest.mark.llm
@pytest.mark.parametrize(
    "candidate_code",
    [_GUARD_CLAUSE_ONLY, _GUARD_AND_INIT, _GUARD_INIT_AND_EMPTY_LOOP],
    ids=["guard_clause_only", "guard_and_init", "guard_init_and_empty_loop"],
)
def test_partial_lookalikes_short_of_the_full_logic_are_low_priority_at_most(
    dry_judge: DryJudge, candidate_code: str
) -> None:
    """Sharing a growing prefix of a function's structure — guard clause,
    init, an empty loop body — is at most a trivial, coincidental overlap.
    The judge may reasonably report it at low priority with "leave as is"
    advice rather than staying silent (that's a legitimate call, not a
    bug), but it must never treat this kind of prefix as a real,
    consolidation-worthy duplicate."""
    candidate = JudgeCandidate(location="legacy/util.py:candidate (lines 1-6)", code=candidate_code)

    incidents = dry_judge.judge(QUERY_WITH_EMBEDDED_TOTAL, [candidate])

    if not incidents:
        return
    assert incidents[0].priority == Priority.LOW


@pytest.mark.llm
def test_diverging_final_step_when_confirmed_excludes_the_line_where_it_diverges(dry_judge: DryJudge) -> None:
    """sum_values_doubled shares the guard/init/loop with the query's
    nested total function but diverges on the final line (it doubles the
    result). Whether the model treats this shared sub-range as worth
    flagging is a genuine judgment call it isn't fully consistent on run to
    run — this only checks precision when it does: the range must never
    extend into line 8's "return result", where the two actually diverge."""
    candidate = JudgeCandidate(location="legacy/util.py:sum_values_doubled (lines 1-7)", code=_SAME_SHAPE_WRONG_RESULT)

    incidents = dry_judge.judge(QUERY_WITH_EMBEDDED_TOTAL, [candidate])

    if not incidents:
        return
    start, end = (int(part) for part in incidents[0].line_position.split("-"))
    assert end <= 7


@pytest.mark.llm
def test_complete_nested_duplicate_is_confirmed_against_its_own_line_range(dry_judge: DryJudge) -> None:
    """A full behavioral match nested inside a wrapper function must be
    confirmed against roughly the nested function's own lines (2-8), not
    the whole wrapper or some unrelated range."""
    candidate = JudgeCandidate(location="legacy/util.py:sum_values (lines 1-6)", code=_COMPLETE_MATCH)

    incidents = dry_judge.judge(QUERY_WITH_EMBEDDED_TOTAL, [candidate])

    assert incidents != []
    start, end = (int(part) for part in incidents[0].line_position.split("-"))
    assert start <= 3
    assert end >= 7


@pytest.mark.llm
def test_money_path_duplicate_is_confirmed_at_high_or_critical(dry_judge: DryJudge) -> None:
    """A duplicated fee calculation on a payment path is exactly the case
    critical exists for — the prompt calibrates toward high when unsure,
    so either is an acceptable, non-trivial priority here."""
    candidate = JudgeCandidate(location="billing/refunds.py:compute_refund_fee (lines 2-4)", code=_PAYMENT_FEE_DUPLICATE)

    incidents = dry_judge.judge(_PAYMENT_QUERY, [candidate])

    assert incidents != []
    assert incidents[0].priority in (Priority.HIGH, Priority.CRITICAL)


@pytest.mark.llm
def test_batched_candidates_each_get_their_own_correct_verdict(dry_judge: DryJudge) -> None:
    """One call judging a true duplicate alongside a false-positive trap
    and an unrelated function must not mix up which verdict belongs to
    which candidate — only the true duplicate should produce an incident."""
    true_duplicate = JudgeCandidate(location="legacy/util.py:sum_values (lines 1-6)", code=_COMPLETE_MATCH)
    guard_trap = JudgeCandidate(location="legacy/other.py:guard_check (lines 1-3)", code=_GUARD_CLAUSE_ONLY)
    unrelated = JudgeCandidate(location="notifications/mailer.py:send_email (lines 1-2)", code=UNRELATED_FUNCTION)

    incidents = dry_judge.judge(QUERY_WITH_EMBEDDED_TOTAL, [true_duplicate, guard_trap, unrelated])

    assert len(incidents) == 1


@pytest.mark.llm
def test_two_separate_duplicated_regions_are_both_confirmed_independently(dry_judge: DryJudge) -> None:
    """A query nesting two unrelated duplicated functions, each matched by
    its own candidate, must report both — not just the first one found."""
    sum_candidate = JudgeCandidate(location="legacy/util.py:sum_all (lines 1-4)", code=_SUM_CANDIDATE_CODE)
    slug_candidate = JudgeCandidate(location="legacy/text.py:slugify (lines 1-2)", code=_SLUG_CANDIDATE_CODE)

    incidents = dry_judge.judge(_MULTI_REGION_QUERY, [sum_candidate, slug_candidate])

    assert len(incidents) == 2


@pytest.mark.llm
def test_identical_logic_is_confirmed_regardless_of_unrelated_domain_naming(dry_judge: DryJudge) -> None:
    """The judge's job is code similarity, not guessing at business intent
    — behaviorally identical logic must be confirmed even when the two
    functions serve conceptually unrelated purposes. Whether to actually
    merge them is a human call, not a gate on reporting the duplicate."""
    candidate = JudgeCandidate(location="scoring/validators.py:is_valid_score (lines 1-3)", code=_INDEPENDENT_DOMAIN_CANDIDATE)

    incidents = dry_judge.judge(_INDEPENDENT_DOMAIN_QUERY, [candidate])

    assert incidents != []
