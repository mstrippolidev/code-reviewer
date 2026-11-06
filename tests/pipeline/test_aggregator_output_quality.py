"""
    Tests that the Aggregator reports what each agent concluded to the metrics hook, and which entries it leaves out.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.pipeline import aggregator
from code_reviewer.pipeline.aggregator import Aggregator
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority, SizeStatus, SkippedFile
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import (
    AGENT_INCIDENT_OVERLAPS,
    AGENT_INCIDENTS,
    AGENT_INVALID_LINE_POSITIONS,
    AGENT_RATING,
    AGENT_RESULTS,
    FILE_SKIPPED,
    REVIEW_RATING,
    point_with,
    points_for,
)

_CODE_KEY = "code_reviewer.code_key"
_AGENT_PAIR = "code_reviewer.agent_pair"
_FILE_CONTENT = "a = 1\nb = 2\nc = 3\n"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    """Points the aggregator at the private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(aggregator, "pipeline_metrics", isolated_pipeline_metrics)


def _prepared_file() -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path="a.py", content=_FILE_CONTENT), size_status=SizeStatus.NORMAL
    )


def _incident(priority: Priority = Priority.LOW, line_position: str = "1-1") -> Incident:
    return Incident(priority=priority, line_position=line_position, description="issue", advice="fix it")


def _entry(code_key: CodeKey, rating: int = 100, incidents: list[Incident] | None = None) -> AgentReviewEntry:
    return AgentReviewEntry(file_path="a.py", code_key=code_key, rating=rating, incidents=incidents or [])


def _build(entries: list[AgentReviewEntry]) -> None:
    Aggregator().build_output(entries, [_prepared_file()], [])


def test_a_clean_entry_is_counted_as_an_empty_result(metric_reader: InMemoryMetricReader) -> None:
    """Verify an agent that found nothing adds to the empty side of the result counter."""
    _build([_entry(CodeKey.VAR)])

    assert point_with(metric_reader, AGENT_RESULTS, {_CODE_KEY: "VAR", "code_reviewer.result": "empty"}).value == 1


def test_an_entry_with_incidents_is_counted_as_with_incidents(metric_reader: InMemoryMetricReader) -> None:
    """Verify an agent that reported something adds to the with_incidents side of the result counter."""
    _build([_entry(CodeKey.VAR, rating=93, incidents=[_incident()])])

    result = point_with(metric_reader, AGENT_RESULTS, {_CODE_KEY: "VAR", "code_reviewer.result": "with_incidents"})
    assert result.value == 1


def test_incidents_are_counted_per_priority(metric_reader: InMemoryMetricReader) -> None:
    """Verify each incident adds one to its own priority series."""
    incidents = [_incident(Priority.HIGH), _incident(Priority.HIGH), _incident(Priority.LOW)]

    _build([_entry(CodeKey.COH, rating=70, incidents=incidents)])

    assert point_with(metric_reader, AGENT_INCIDENTS, {_CODE_KEY: "COH", "code_reviewer.priority": "high"}).value == 2
    assert point_with(metric_reader, AGENT_INCIDENTS, {_CODE_KEY: "COH", "code_reviewer.priority": "low"}).value == 1


def test_the_agent_rating_is_recorded(metric_reader: InMemoryMetricReader) -> None:
    """Verify the rating of a real judgment lands in the agent's rating histogram."""
    _build([_entry(CodeKey.VAR, rating=73)])

    rating = point_with(metric_reader, AGENT_RATING, {_CODE_KEY: "VAR"})
    assert (rating.count, rating.sum) == (1, 73)


def test_an_incident_outside_the_file_is_counted_as_invalid(metric_reader: InMemoryMetricReader) -> None:
    """Verify a line_position past the file's last line raises the invalid counter."""
    incidents = [_incident(line_position="2-3"), _incident(line_position="2-40")]

    _build([_entry(CodeKey.VAR, rating=90, incidents=incidents)])

    assert point_with(metric_reader, AGENT_INVALID_LINE_POSITIONS, {_CODE_KEY: "VAR"}).value == 1


def test_the_last_line_of_a_file_without_a_trailing_newline_is_valid(metric_reader: InMemoryMetricReader) -> None:
    """Verify a range ending on the final line is valid even when the file has no closing newline."""
    prepared_file = PreparedFile(
        source_file=SubmittedFile(file_path="a.py", content="a = 1\nb = 2"), size_status=SizeStatus.NORMAL
    )
    entry = _entry(CodeKey.VAR, rating=97, incidents=[_incident(line_position="1-2")])

    Aggregator().build_output([entry], [prepared_file], [])

    assert point_with(metric_reader, AGENT_INVALID_LINE_POSITIONS, {_CODE_KEY: "VAR"}).value == 0


def test_a_failed_entry_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify an agent whose run failed adds no result, because its rating and incidents carry no signal."""
    failed_entry = _entry(CodeKey.VAR)
    failed_entry.failed = True

    _build([failed_entry])

    assert points_for(metric_reader, AGENT_RESULTS) == []


def test_a_skipped_entry_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify an agent that did not apply to the submission adds no result."""
    skipped_entry = _entry(CodeKey.DRY)
    skipped_entry.skipped = True

    _build([skipped_entry])

    assert points_for(metric_reader, AGENT_RESULTS) == []


def test_a_hard_limit_entry_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify a rating-0 hard-limit result is left out, since it is deterministic and would read as drift."""
    _build([_entry(CodeKey.COH, rating=0, incidents=[_incident(Priority.HIGH)])])

    assert points_for(metric_reader, AGENT_RATING) == []


def test_two_agents_pointing_at_the_same_lines_are_counted_as_an_overlap(metric_reader: InMemoryMetricReader) -> None:
    """Verify the overlap lands on the series of the two agents that raised it."""
    _build([
        _entry(CodeKey.SOLID2, incidents=[_incident(line_position="2-3")]),
        _entry(CodeKey.TEST, incidents=[_incident(line_position="3-3")]),
    ])

    assert point_with(metric_reader, AGENT_INCIDENT_OVERLAPS, {_AGENT_PAIR: "SOLID2+TEST"}).value == 1


def test_incidents_on_different_lines_are_not_an_overlap(metric_reader: InMemoryMetricReader) -> None:
    """Verify two agents flagging different places add nothing."""
    _build([
        _entry(CodeKey.SOLID2, incidents=[_incident(line_position="1-1")]),
        _entry(CodeKey.TEST, incidents=[_incident(line_position="3-3")]),
    ])

    assert points_for(metric_reader, AGENT_INCIDENT_OVERLAPS) == []


def test_an_incident_spanning_the_whole_file_is_not_counted_as_an_overlap(metric_reader: InMemoryMetricReader) -> None:
    """Verify a size-limit style incident, which covers every line, does not overlap with everything."""
    _build([
        _entry(CodeKey.CMPLX, incidents=[_incident(line_position="1-3")]),
        _entry(CodeKey.TEST, incidents=[_incident(line_position="2-2")]),
    ])

    assert points_for(metric_reader, AGENT_INCIDENT_OVERLAPS) == []


def test_a_hard_limit_entry_adds_no_overlap(metric_reader: InMemoryMetricReader) -> None:
    """Verify the fixed rating-0 incident of a file that was too large is not read as agents agreeing."""
    _build([
        _entry(CodeKey.COH, rating=0, incidents=[_incident(Priority.HIGH, line_position="1-3")]),
        _entry(CodeKey.TEST, incidents=[_incident(line_position="2-2")]),
    ])

    assert points_for(metric_reader, AGENT_INCIDENT_OVERLAPS) == []


def test_a_failed_agent_adds_no_overlap(metric_reader: InMemoryMetricReader) -> None:
    """Verify an agent that did not judge the file cannot overlap with one that did."""
    failed = AgentReviewEntry(
        file_path="a.py", code_key=CodeKey.COUP, rating=0, failed=True, incidents=[_incident(line_position="2-2")]
    )
    _build([failed, _entry(CodeKey.TEST, incidents=[_incident(line_position="2-2")])])

    assert points_for(metric_reader, AGENT_INCIDENT_OVERLAPS) == []


def test_every_skipped_file_is_counted_under_its_reason(metric_reader: InMemoryMetricReader) -> None:
    """Verify each reason in the report becomes its own series, with repeated reasons added up."""
    skipped = [
        SkippedFile(file_path="a.py", reason="intake_rejected"),
        SkippedFile(file_path="b.py", reason="intake_rejected"),
        SkippedFile(file_path="c.py", reason="exceeded_pr_file_cap"),
    ]

    Aggregator().build_output([_entry(CodeKey.VAR)], [_prepared_file()], skipped)

    assert point_with(metric_reader, FILE_SKIPPED, {"code_reviewer.reason": "intake_rejected"}).value == 2
    assert point_with(metric_reader, FILE_SKIPPED, {"code_reviewer.reason": "exceeded_pr_file_cap"}).value == 1


def test_a_review_with_no_skipped_files_records_no_skips(metric_reader: InMemoryMetricReader) -> None:
    """Verify the counter stays empty when nothing was left out."""
    _build([_entry(CodeKey.VAR)])

    assert points_for(metric_reader, FILE_SKIPPED) == []


def test_the_overall_rating_is_recorded_once_per_review(metric_reader: InMemoryMetricReader) -> None:
    """Verify one finished review adds exactly one point to the overall rating histogram."""
    _build([_entry(CodeKey.VAR, rating=80)])

    overall = points_for(metric_reader, REVIEW_RATING)[0]
    assert (overall.count, overall.sum) == (1, 80)
