"""
    The exemplar judge against a real model, on the fast tier the jury's members run on: a candidate on the
    same design problem as the code under review is relevant, and candidates from another domain or about
    another principle are not.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag.exemplar_judge import ExemplarJudge
from code_reviewer.rag.exemplars import Exemplar
from code_reviewer.schemas.review import CodeKey

pytestmark = pytest.mark.llm

CODE_UNDER_REVIEW = '''def calculate_order_total(items, payment_type):
    total = sum(item.price for item in items)
    if payment_type == "credit_card":
        return total * 1.03
    elif payment_type == "paypal":
        return total * 1.05
    elif payment_type == "bank_transfer":
        return total + 2
    return total
'''

SAME_PROBLEM = Exemplar(
    code_key=CodeKey.SOLID1,
    file_path="billing/payments.py",
    chunk_name="PaymentMethod",
    code='''class PaymentMethod(ABC):
    @abstractmethod
    def fee(self, total: float) -> float: ...


class CreditCardPayment(PaymentMethod):
    def fee(self, total: float) -> float:
        return total * 0.03


def calculate_order_total(items, payment_method: PaymentMethod) -> float:
    total = sum(item.price for item in items)
    return total + payment_method.fee(total)
''',
    score=0.2,
)

OTHER_DOMAIN = Exemplar(
    code_key=CodeKey.SOLID1,
    file_path="parsing/csv_reader.py",
    chunk_name="parse_csv_line",
    code='''def parse_csv_line(line: str) -> list[str]:
    fields, current, in_quotes = [], "", False
    for character in line:
        if character == '"':
            in_quotes = not in_quotes
        elif character == "," and not in_quotes:
            fields.append(current)
            current = ""
        else:
            current += character
    fields.append(current)
    return fields
''',
    score=0.1,
)

OTHER_PRINCIPLE = Exemplar(
    code_key=CodeKey.SOLID1,
    file_path="accounts/withdrawals.py",
    chunk_name="withdraw",
    code='''class InsufficientFundsError(Exception):
    """Raised when a withdrawal is larger than the balance."""


def withdraw(account, amount: int) -> None:
    if amount > account.balance:
        raise InsufficientFundsError(f"{amount} exceeds balance {account.balance}")
    account.balance -= amount
''',
    score=0.1,
)

CANDIDATES = [SAME_PROBLEM, OTHER_DOMAIN, OTHER_PRINCIPLE]


@pytest.fixture(scope="module")
def picked(small_llm: LLMInterface) -> list[Exemplar]:
    return ExemplarJudge(small_llm.for_fast_tier()).pick_relevant(CodeKey.SOLID1, CODE_UNDER_REVIEW, CANDIDATES)


def test_an_example_on_the_same_design_problem_is_relevant(picked: list[Exemplar]) -> None:
    """Verify the strategy-pattern fix for a payment-type if/elif chain counts as a reference for it."""
    assert SAME_PROBLEM in picked


def test_an_example_from_an_unrelated_domain_is_not_relevant(picked: list[Exemplar]) -> None:
    """Verify a CSV parser is not offered as a reference for payment-fee code just because both are Python."""
    assert OTHER_DOMAIN not in picked


def test_an_example_of_a_different_principle_is_not_relevant(picked: list[Exemplar]) -> None:
    """Verify good error handling is not offered as a reference when the principle checked is single
    responsibility and open/closed."""
    assert OTHER_PRINCIPLE not in picked
