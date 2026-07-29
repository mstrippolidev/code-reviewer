import pytest
from guardrails.validators import FailResult, PassResult

from code_reviewer.guardrails.validators.code_detection import CodeDetectionValidator

pytestmark = pytest.mark.llm

REAL_PYTHON_FUNCTION = """
def calculate_total(items: list[float]) -> float:
    total = 0.0
    for item in items:
        total += item
    return total
"""

PROSE_TEXT = """
Our quarterly roadmap review is scheduled for next Thursday. Please come
prepared to discuss the migration timeline and any blockers your team is
facing with the new deployment pipeline.
"""


def test_accepts_real_python_code(small_llm) -> None:
    validator = CodeDetectionValidator(llm=small_llm)

    result = validator._validate(REAL_PYTHON_FUNCTION, {})

    assert isinstance(result, PassResult)


def test_rejects_prose_text(small_llm) -> None:
    validator = CodeDetectionValidator(llm=small_llm)

    result = validator._validate(PROSE_TEXT, {})

    assert isinstance(result, FailResult)
