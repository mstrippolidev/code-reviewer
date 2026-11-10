"""
    Deterministic check that a review is about the code it was asked to review.
"""
import builtins
import keyword
import re

from code_reviewer.pipeline.line_offset import parse_line_range
from code_reviewer.schemas.review import AgentOutput, Incident

QUOTED_SPAN = re.compile(r"`([^`]+)`")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MIN_NAME_LENGTH = 3
GENERIC_NAMES = frozenset(keyword.kwlist) | frozenset(dir(builtins))


def is_review_invented(output: AgentOutput, code: str, checks_quoted_names: bool = True) -> bool:
    """True when the review has incidents and every one of them is about code that is not in `code`."""
    incidents = [incident for entry in output.review for incident in entry.incidents]
    code_names = set(IDENTIFIER.findall(code))
    line_count = len(code.splitlines())
    return bool(incidents) and all(
        _is_ungrounded(incident, code_names, line_count, checks_quoted_names) for incident in incidents
    )


def _is_ungrounded(incident: Incident, code_names: set[str], line_count: int, checks_quoted_names: bool) -> bool:
    if _outside_file(incident.line_position, line_count):
        return True
    return checks_quoted_names and _quotes_only_missing_names(incident.description, code_names)


def _outside_file(line_position: str, line_count: int) -> bool:
    """A malformed range is a formatting slip, not evidence of invented code, so it never counts."""
    try:
        start, end = parse_line_range(line_position)
    except ValueError:
        return False
    return start <= end and (start < 1 or end > line_count)


def _quotes_only_missing_names(description: str, code_names: set[str]) -> bool:
    """True when the description quotes names of its own and none of them appears in the code."""
    quoted = _quoted_names(description)
    return bool(quoted) and quoted.isdisjoint(code_names)


def _quoted_names(text: str) -> set[str]:
    spans = QUOTED_SPAN.findall(text)
    names = {name for span in spans for name in IDENTIFIER.findall(span)}
    return {name for name in names if len(name) >= MIN_NAME_LENGTH and name not in GENERIC_NAMES}
