"""
    Tests for reading an agent's result: the most severe priority and incidents pointing outside the file.
"""
import pytest

from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority
from evaluation.incidents import count_invalid_lines, highest_priority, is_inside_file


def make_entry(*line_positions: str) -> AgentReviewEntry:
    incidents = [
        Incident(priority=Priority.LOW, line_position=position, description="d", advice="a") for position in line_positions
    ]
    return AgentReviewEntry(file_path="f.py", rating=90, code_key=CodeKey.VAR, incidents=incidents)


@pytest.mark.parametrize("line_position", ["1-1", "5-21", "21-21"])
def test_a_range_inside_the_file_is_valid(line_position: str) -> None:
    """Verify ranges within a 21-line file, including its first and last line, are accepted."""
    assert is_inside_file(line_position, line_count=21)


@pytest.mark.parametrize("line_position", ["0-3", "22-22", "46-87", "9-5", "12", "a-b"])
def test_a_range_outside_or_malformed_is_invalid(line_position: str) -> None:
    """Verify a range past the file, before line 1, reversed or unparseable is rejected."""
    assert not is_inside_file(line_position, line_count=21)


def test_count_invalid_lines_counts_only_the_incidents_outside_the_file() -> None:
    """Verify an entry with one valid and two out-of-file incidents reports 2."""
    entry = make_entry("3-4", "46-87", "93-126")

    assert count_invalid_lines(entry, line_count=21) == 2


def test_highest_priority_of_an_entry_without_incidents_is_none() -> None:
    """Verify a clean entry has no highest priority."""
    assert highest_priority(make_entry()) is None
