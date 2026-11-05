"""
    Derives the quality signals of one agent review entry, without touching any instrument.
"""
from pydantic import BaseModel

from code_reviewer.schemas.review import AgentReviewEntry


class OutputQuality(BaseModel):
    rating: int
    incident_priorities: list[str]
    invalid_line_positions: int

    @property
    def is_empty(self) -> bool:
        return not self.incident_priorities


def assess_entry(entry: AgentReviewEntry, file_line_count: int) -> OutputQuality:
    """Counts an entry's incidents by priority and those whose line_position falls outside the file."""
    return OutputQuality(
        rating=entry.rating,
        incident_priorities=[incident.priority.value for incident in entry.incidents],
        invalid_line_positions=sum(
            not _is_valid_line_range(incident.line_position, file_line_count) for incident in entry.incidents
        ),
    )


def _is_valid_line_range(line_position: str, file_line_count: int) -> bool:
    """A 'start-end' string with 1 <= start <= end <= file_line_count; anything else is invalid."""
    start, separator, end = line_position.partition("-")
    if not (separator and start.isdecimal() and end.isdecimal()):
        return False
    return 1 <= int(start) <= int(end) <= file_line_count
