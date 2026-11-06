"""
    Tests which incidents of different agents count as pointing at the same lines.
"""
from code_reviewer.schemas.review import AttributedIncident, CodeKey, Priority
from code_reviewer.telemetry.incident_overlap import overlapping_agent_pairs


def _incident(code_key: CodeKey, line_position: str) -> AttributedIncident:
    return AttributedIncident(
        code_key=code_key, priority=Priority.LOW, line_position=line_position, description="issue", advice="fix it"
    )


def test_no_incidents_have_no_overlaps() -> None:
    """Verify an empty file report is not an error."""
    assert overlapping_agent_pairs([]) == []


def test_two_agents_on_the_same_lines_overlap() -> None:
    """Verify the pair is named after both agents."""
    incidents = [_incident(CodeKey.SOLID2, "10-20"), _incident(CodeKey.TEST, "10-20")]

    assert overlapping_agent_pairs(incidents) == ["SOLID2+TEST"]


def test_a_partial_overlap_counts() -> None:
    """Verify sharing some lines is enough, not only identical ranges."""
    incidents = [_incident(CodeKey.COH, "10-20"), _incident(CodeKey.COUP, "15-30")]

    assert overlapping_agent_pairs(incidents) == ["COH+COUP"]


def test_ranges_that_touch_at_one_line_overlap() -> None:
    """Verify the boundary line is shared, so 10-20 and 20-30 point at the same line."""
    incidents = [_incident(CodeKey.COH, "10-20"), _incident(CodeKey.COUP, "20-30")]

    assert overlapping_agent_pairs(incidents) == ["COH+COUP"]


def test_ranges_that_only_sit_next_to_each_other_do_not_overlap() -> None:
    """Verify 10-20 and 21-30 share no line."""
    incidents = [_incident(CodeKey.COH, "10-20"), _incident(CodeKey.COUP, "21-30")]

    assert overlapping_agent_pairs(incidents) == []


def test_a_range_inside_another_overlaps() -> None:
    """Verify containment counts."""
    incidents = [_incident(CodeKey.ARCH, "1-100"), _incident(CodeKey.VAR, "40-41")]

    assert overlapping_agent_pairs(incidents) == ["ARCH+VAR"]


def test_one_agent_overlapping_itself_is_ignored() -> None:
    """Verify two incidents of the same agent are not a disagreement between agents."""
    incidents = [_incident(CodeKey.VAR, "10-20"), _incident(CodeKey.VAR, "10-20")]

    assert overlapping_agent_pairs(incidents) == []


def test_the_pair_name_does_not_depend_on_incident_order() -> None:
    """Verify TEST first and SOLID2 first give the same series."""
    forward = overlapping_agent_pairs([_incident(CodeKey.SOLID2, "5-9"), _incident(CodeKey.TEST, "5-9")])
    backward = overlapping_agent_pairs([_incident(CodeKey.TEST, "5-9"), _incident(CodeKey.SOLID2, "5-9")])

    assert forward == backward == ["SOLID2+TEST"]


def test_three_agents_on_one_range_make_three_pairs() -> None:
    """Verify every pair of agents is counted, not only the first."""
    incidents = [_incident(CodeKey.COH, "1-9"), _incident(CodeKey.COUP, "1-9"), _incident(CodeKey.TEST, "1-9")]

    assert sorted(overlapping_agent_pairs(incidents)) == ["COH+COUP", "COH+TEST", "COUP+TEST"]


def test_malformed_and_backwards_positions_are_ignored() -> None:
    """Verify a bad position neither raises nor overlaps, since invalid positions are counted elsewhere."""
    incidents = [
        _incident(CodeKey.COH, "10-20"),
        _incident(CodeKey.COUP, "not-a-range"),
        _incident(CodeKey.TEST, "30-10"),
        _incident(CodeKey.VAR, "15"),
    ]

    assert overlapping_agent_pairs(incidents) == []
