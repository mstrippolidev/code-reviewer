import pytest
from pydantic import ValidationError

from code_reviewer.schemas.review import (
    AgentOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    Priority,
    SkippedFile,
)


def _incident(**overrides) -> dict:
    base = {
        "priority": Priority.HIGH,
        "line_position": "10-20",
        "description": "Something is wrong",
        "advice": "Fix it",
    }
    return {**base, **overrides}


def test_incident_accepts_valid_fields() -> None:
    incident = Incident(**_incident())

    assert incident.priority == Priority.HIGH
    assert incident.code_key is None


def test_incident_rejects_invalid_priority() -> None:
    with pytest.raises(ValidationError):
        Incident(**_incident(priority="urgent"))


@pytest.mark.parametrize("rating", [-1, 101])
def test_agent_review_entry_rejects_out_of_range_rating(rating: int) -> None:
    with pytest.raises(ValidationError):
        AgentReviewEntry(rating=rating, code_key=CodeKey.VAR, incidents=[])


def test_agent_review_entry_accepts_rating_100_with_no_incidents() -> None:
    entry = AgentReviewEntry(rating=100, code_key=CodeKey.VAR, incidents=[])

    assert entry.rating == 100


def test_agent_review_entry_accepts_rating_0_with_incidents() -> None:
    entry = AgentReviewEntry(rating=0, code_key=CodeKey.VAR, incidents=[Incident(**_incident())])

    assert entry.rating == 0


def test_agent_review_entry_rejects_discounted_rating_with_no_incidents() -> None:
    with pytest.raises(ValidationError):
        AgentReviewEntry(rating=85, code_key=CodeKey.VAR, incidents=[])


def test_agent_review_entry_rejects_full_rating_with_incidents() -> None:
    with pytest.raises(ValidationError):
        AgentReviewEntry(rating=100, code_key=CodeKey.VAR, incidents=[Incident(**_incident())])


def test_agent_review_entry_rejects_unknown_code_key() -> None:
    with pytest.raises(ValidationError):
        AgentReviewEntry(rating=50, code_key="NOT_REAL", incidents=[])


def test_agent_output_holds_multiple_review_entries() -> None:
    output = AgentOutput(
        review=[
            AgentReviewEntry(rating=100, code_key=CodeKey.VAR, incidents=[]),
            AgentReviewEntry(rating=60, code_key=CodeKey.VAR, incidents=[Incident(**_incident())]),
        ]
    )

    assert len(output.review) == 2


def test_skipped_file_requires_path_and_reason() -> None:
    skipped = SkippedFile(file_path="a.py", reason="exceeded_pr_file_cap")

    assert skipped.reason == "exceeded_pr_file_cap"
