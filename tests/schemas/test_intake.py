import pytest
from pydantic import ValidationError

from code_reviewer.schemas.intake import ScreeningVerdict


def test_screening_verdict_accepts_valid_fields() -> None:
    verdict = ScreeningVerdict(is_valid=False, reason="Contains a prompt-injection attempt.")

    assert verdict.is_valid is False
    assert verdict.reason == "Contains a prompt-injection attempt."


def test_screening_verdict_requires_is_valid() -> None:
    with pytest.raises(ValidationError):
        ScreeningVerdict(reason="No is_valid given.")
