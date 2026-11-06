"""
    Finds the incidents of different agents that point at the same lines, without touching any instrument.
"""
from collections.abc import Sequence
from itertools import combinations

from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.schemas.review import AttributedIncident


def overlapping_agent_pairs(incidents: Sequence[AttributedIncident]) -> list[str]:
    """One 'A+B' (names sorted) for each pair of incidents from two different agents that share a line."""
    located = [(incident.code_key.value, _line_range(incident.line_position)) for incident in incidents]
    located = [(agent, line_range) for agent, line_range in located if line_range is not None]
    return [
        "+".join(sorted((agent_a, agent_b)))
        for (agent_a, range_a), (agent_b, range_b) in combinations(located, 2)
        if agent_a != agent_b and range_a[0] <= range_b[1] and range_b[0] <= range_a[1]
    ]


def _line_range(line_position: str) -> tuple[int, int] | None:
    """A 'start-end' range, or None when it is malformed or runs backwards."""
    try:
        start, end = parse_line_range(line_position)
    except ValueError:
        return None
    return (start, end) if start <= end else None
