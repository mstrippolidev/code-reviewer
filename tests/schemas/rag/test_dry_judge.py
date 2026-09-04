import pytest
from pydantic import ValidationError

from code_reviewer.schemas.rag.dry_judge import DryJudgeOutput, DryJudgeVerdict
from code_reviewer.schemas.review import Priority


def _confirmed(**overrides) -> dict:
    base = {
        "candidate_index": 0,
        "is_duplicate": True,
        "priority": Priority.HIGH,
        "line_position": "10-20",
        "description": "Duplicated logic",
        "advice": "Extract a shared function",
    }
    return {**base, **overrides}


def test_confirmed_duplicate_with_every_field_set_is_valid() -> None:
    verdict = DryJudgeVerdict(**_confirmed())

    assert verdict.is_duplicate is True


def test_unconfirmed_candidate_needs_no_finding_fields() -> None:
    verdict = DryJudgeVerdict(candidate_index=0, is_duplicate=False)

    assert verdict.priority is None
    assert verdict.line_position is None


@pytest.mark.parametrize("missing_field", ["priority", "line_position", "description", "advice"])
def test_confirmed_duplicate_missing_any_finding_field_is_rejected(missing_field: str) -> None:
    with pytest.raises(ValidationError):
        DryJudgeVerdict(**_confirmed(**{missing_field: None}))


def test_confirmed_duplicate_with_every_finding_field_missing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DryJudgeVerdict(candidate_index=0, is_duplicate=True)


def test_output_requires_at_least_one_verdict() -> None:
    with pytest.raises(ValidationError):
        DryJudgeOutput(verdicts=[])


def test_output_accepts_a_mix_of_confirmed_and_unconfirmed_verdicts() -> None:
    output = DryJudgeOutput(
        verdicts=[
            DryJudgeVerdict(**_confirmed(candidate_index=0)),
            DryJudgeVerdict(candidate_index=1, is_duplicate=False),
        ]
    )

    assert len(output.verdicts) == 2
