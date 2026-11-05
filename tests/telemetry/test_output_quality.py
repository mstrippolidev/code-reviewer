"""
    Tests for assess_entry: pure derivation of an agent entry's quality signals, no instruments involved.
"""
import pytest

from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority
from code_reviewer.telemetry.output_quality import assess_entry

_FILE_LINE_COUNT = 100


def _incident(priority: Priority = Priority.LOW, line_position: str = "1-1") -> Incident:
    return Incident(priority=priority, line_position=line_position, description="issue", advice="fix it")


def _entry(incidents: list[Incident], rating: int = 100) -> AgentReviewEntry:
    return AgentReviewEntry(code_key=CodeKey.VAR, rating=rating, incidents=incidents)


def test_an_entry_without_incidents_is_empty() -> None:
    """Verify a clean result is reported as empty, which is what the empty-result rate counts."""
    quality = assess_entry(_entry([]), _FILE_LINE_COUNT)

    assert quality.is_empty


def test_an_entry_with_incidents_is_not_empty() -> None:
    """Verify any incident makes the result non-empty."""
    quality = assess_entry(_entry([_incident()]), _FILE_LINE_COUNT)

    assert not quality.is_empty


def test_incident_priorities_are_listed_one_per_incident() -> None:
    """Verify each incident contributes its own priority, so the counter can be incremented per incident."""
    incidents = [_incident(Priority.HIGH), _incident(Priority.HIGH), _incident(Priority.LOW)]

    quality = assess_entry(_entry(incidents), _FILE_LINE_COUNT)

    assert quality.incident_priorities == ["high", "high", "low"]


def test_the_entry_rating_is_carried_over() -> None:
    """Verify the rating the agent ended with is the one reported."""
    quality = assess_entry(_entry([], rating=73), _FILE_LINE_COUNT)

    assert quality.rating == 73


@pytest.mark.parametrize("line_position", ["1-1", "5-9", "1-100", "100-100"])
def test_a_range_inside_the_file_is_valid(line_position: str) -> None:
    """Verify ranges from the first to the last line of the file are not counted as invalid."""
    quality = assess_entry(_entry([_incident(line_position=line_position)]), _FILE_LINE_COUNT)

    assert quality.invalid_line_positions == 0


@pytest.mark.parametrize("line_position", ["0-3", "9-5", "5-101", "12", "a-b", "-3-5", "5-", ""])
def test_a_malformed_or_out_of_range_position_is_invalid(line_position: str) -> None:
    """Verify a position that is not a 'start-end' range inside the file is counted as invalid."""
    quality = assess_entry(_entry([_incident(line_position=line_position)]), _FILE_LINE_COUNT)

    assert quality.invalid_line_positions == 1


def test_only_the_invalid_incidents_are_counted() -> None:
    """Verify a valid incident next to an invalid one does not raise the count."""
    incidents = [_incident(line_position="3-4"), _incident(line_position="3-400")]

    quality = assess_entry(_entry(incidents), _FILE_LINE_COUNT)

    assert quality.invalid_line_positions == 1
