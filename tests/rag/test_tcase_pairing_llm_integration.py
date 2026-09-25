"""
    TCASE pairing judge and query rewrite against a real model, on the fast
    tier the registry wires them to.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.tcase_pairing import PairingCandidate
from code_reviewer.rag.tcase_pairing_judge import PairingJudge
from code_reviewer.rag.tcase_pairing_query_rewrite import PairingQueryRewriter
from code_reviewer.schemas.rag.tcase_pairing import PairingMatchStatus, PairingVerdict
from code_reviewer.schemas.submission import SubmittedFile

pytestmark = pytest.mark.llm

SOURCE = SubmittedFile(
    file_path="shop/payment.py",
    content='''class DeclinedCardError(Exception):
    pass


def charge(amount: int, card_number: str) -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    if card_number.startswith("4000"):
        raise DeclinedCardError(card_number)
    return amount
''',
)

GENUINE_TEST = PairingCandidate(
    file_path="tests/test_payment.py",
    content='''def test_charge_returns_the_charged_amount():
    assert charge(500, "4242424242424242") == 500

def test_charge_with_a_declined_card_raises():
    with pytest.raises(DeclinedCardError):
        charge(500, "4000000000000002")
''',
)

DECOY_TEST = PairingCandidate(
    file_path="tests/test_refunds.py",
    content='''def test_refund_restores_the_order_total():
    order = Order(total=900)
    refund(order, amount=300)
    assert order.total == 1200

def test_refund_of_a_cancelled_order_is_rejected():
    with pytest.raises(OrderCancelledError):
        refund(Order(total=900, cancelled=True), amount=100)
''',
)


@pytest.fixture(scope="module")
def verdicts(small_llm: LLMInterface) -> list[PairingVerdict]:
    return PairingJudge(small_llm.for_fast_tier()).judge(SOURCE, [GENUINE_TEST, DECOY_TEST])


def _status_for(verdicts: list[PairingVerdict], candidate_index: int) -> PairingMatchStatus:
    return next(verdict.status for verdict in verdicts if verdict.candidate_index == candidate_index)


def test_judge_confirms_a_test_file_exercising_the_sources_own_symbols(verdicts: list[PairingVerdict]) -> None:
    """Verify tests calling charge and asserting its behavior are judged a match."""
    assert _status_for(verdicts, 0) == PairingMatchStatus.MATCH


def test_judge_rejects_a_test_file_for_a_different_module(verdicts: list[PairingVerdict]) -> None:
    """Verify a same-domain test file exercising refund, which the source never defines, is not a match."""
    assert _status_for(verdicts, 1) == PairingMatchStatus.NO_MATCH


def test_rewritten_query_names_the_sources_own_symbols(small_llm: LLMInterface) -> None:
    """Verify the retry query steers toward the source's real symbols rather than the rejected candidate's.

    The rejection says the only candidate tested refund; the rewrite should
    describe tests of charge instead.
    """
    rejection_reasons = ["It tests refund() and Order totals, which shop/payment.py does not define."]

    query = PairingQueryRewriter(small_llm.for_fast_tier()).rewrite(SOURCE, rejection_reasons)

    assert "charge" in query.lower()
