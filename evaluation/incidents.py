"""
    Reading an agent's result the way labels are compared against it.
"""
from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.schemas.review import AgentReviewEntry, Priority

PRIORITY_RANK = {Priority.LOW: 1, Priority.MEDIUM: 2, Priority.HIGH: 3, Priority.CRITICAL: 4}


def highest_priority(entry: AgentReviewEntry) -> Priority | None:
    """The most severe priority among an entry's incidents, None when it has none."""
    return max((incident.priority for incident in entry.incidents), key=PRIORITY_RANK.get, default=None)


def is_inside_file(line_position: str, line_count: int) -> bool:
    """True when a "start-end" range is well formed and lies within the file's lines."""
    try:
        start, end = parse_line_range(line_position)
    except ValueError:
        return False
    return 1 <= start <= end <= line_count


def count_invalid_lines(entry: AgentReviewEntry, line_count: int) -> int:
    """How many incidents point outside the file, a sign the model described code it was not given."""
    return sum(1 for incident in entry.incidents if not is_inside_file(incident.line_position, line_count))
