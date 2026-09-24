"""
    Tests for DryJudge's own post-processing of a model's verdicts, pure
    Python, no LLM: which confirmed verdicts merge into one incident.
"""
from code_reviewer.rag.dry_judge import JudgeCandidate, _incidents_from_verdicts
from code_reviewer.schemas.rag.dry_judge import DryJudgeVerdict
from code_reviewer.schemas.review import Priority

_CANDIDATE_A = JudgeCandidate(location="handlers.py:not_found (lines 15-27)", code="...")
_CANDIDATE_B = JudgeCandidate(location="handlers.py:conflict (lines 30-42)", code="...")


def _verdict(
    candidate_index: int,
    is_duplicate: bool = True,
    priority: Priority = Priority.HIGH,
    line_position: str = "1-13",
    description: str = "duplicated",
    advice: str = "extract it",
) -> DryJudgeVerdict:
    return DryJudgeVerdict(
        candidate_index=candidate_index,
        is_duplicate=is_duplicate,
        priority=priority if is_duplicate else None,
        line_position=line_position if is_duplicate else None,
        description=description if is_duplicate else None,
        advice=advice if is_duplicate else None,
    )


def test_unconfirmed_verdict_produces_no_incident() -> None:
    verdicts = [_verdict(candidate_index=0, is_duplicate=False)]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A])

    assert incidents == []


def test_single_confirmed_verdict_produces_one_incident_with_its_own_fields() -> None:
    verdicts = [_verdict(candidate_index=0, priority=Priority.MEDIUM, line_position="3-6")]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A])

    assert len(incidents) == 1
    assert incidents[0].priority == Priority.MEDIUM
    assert incidents[0].line_position == "3-6"


def test_overlapping_confirmed_verdicts_merge_into_one_incident() -> None:
    verdicts = [
        _verdict(candidate_index=0, line_position="1-13"),
        _verdict(candidate_index=1, line_position="1-13"),
    ]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A, _CANDIDATE_B])

    assert len(incidents) == 1


def test_merged_incident_names_every_location_in_the_group() -> None:
    verdicts = [
        _verdict(candidate_index=0, line_position="1-13"),
        _verdict(candidate_index=1, line_position="1-13"),
    ]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A, _CANDIDATE_B])

    assert _CANDIDATE_A.location in incidents[0].description
    assert _CANDIDATE_B.location in incidents[0].description


def test_merged_incident_takes_the_highest_priority_in_the_group() -> None:
    verdicts = [
        _verdict(candidate_index=0, line_position="1-13", priority=Priority.LOW),
        _verdict(candidate_index=1, line_position="1-13", priority=Priority.CRITICAL),
    ]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A, _CANDIDATE_B])

    assert incidents[0].priority == Priority.CRITICAL


def test_merged_incident_line_position_spans_the_group() -> None:
    verdicts = [
        _verdict(candidate_index=0, line_position="1-5"),
        _verdict(candidate_index=1, line_position="4-13"),
    ]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A, _CANDIDATE_B])

    assert incidents[0].line_position == "1-13"


def test_disjoint_confirmed_verdicts_stay_as_separate_incidents() -> None:
    verdicts = [
        _verdict(candidate_index=0, line_position="1-4"),
        _verdict(candidate_index=1, line_position="10-11"),
    ]

    incidents = _incidents_from_verdicts(verdicts, [_CANDIDATE_A, _CANDIDATE_B])

    assert len(incidents) == 2
