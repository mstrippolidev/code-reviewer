"""
    Tests for the markdown account of missed labels: hand-built results, no model.
"""
from datetime import datetime, timezone

from code_reviewer.schemas.review import Incident, Priority
from evaluation.labels import FixtureLabel
from evaluation.scoring import EvaluationReport, LabelResult, score_agent
from evaluation.transcript import RunTranscript, TranscriptMessage
from evaluation.transcript_report import render_reasoning_log, render_transcript_report

LOG_NAME = "20261109-000000-bound-reasoning.log"


def make_report(results: list[LabelResult]) -> EvaluationReport:
    return EvaluationReport(
        model_by_agent={"bound": "model-x"},
        runs_per_label=1,
        created_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        scores=[score_agent("bound", results)],
        results={"bound": results},
    )


def make_label() -> FixtureLabel:
    return FixtureLabel(id="clear-medium", fixture="shared/x.py", path="x.py", expected=Priority.MEDIUM, reason="built as medium")


def make_missed_result(invalid_lines_per_run: list[int]) -> LabelResult:
    incident = Incident(priority=Priority.HIGH, line_position="3-4", description="public dict", advice="hide it")
    message = TranscriptMessage(
        role="assistant",
        text="done",
        reasoning="the dict is the store",
        reply_details={"finish_reason": "stop"},
    )
    return LabelResult(
        label=make_label(),
        highest_per_run=[Priority.HIGH],
        incidents_per_run=[[incident]],
        transcripts_per_run=[RunTranscript(messages=[message])],
        invalid_lines_per_run=invalid_lines_per_run,
    )


def test_a_missed_run_shows_its_incidents_and_answer_without_the_reasoning() -> None:
    """Verify the markdown marks the missed run and its answer, and points to the log instead of holding the reasoning."""
    text = render_transcript_report(make_report([make_missed_result([0])]), LOG_NAME)

    assert "answered high (MISSED)" in text
    assert "[high] 3-4: public dict" in text
    assert "Reply: finish_reason=stop" in text
    assert "Reasoning: 21 characters, in the reasoning log." in text
    assert LOG_NAME in text
    assert "the dict is the store" not in text


def test_the_reasoning_log_holds_the_reasoning_of_each_missed_run() -> None:
    """Verify the reasoning log names the label and run and holds the reasoning text."""
    log = render_reasoning_log(make_report([make_missed_result([0])]))

    assert "=== clear-medium / run 1 ===" in log
    assert "the dict is the store" in log


def test_a_run_with_incidents_outside_the_file_is_flagged() -> None:
    """Verify a run whose incidents point outside the fixture is marked as possibly about other code."""
    text = render_transcript_report(make_report([make_missed_result([2])]), LOG_NAME)

    assert "answered high (MISSED) (ANSWER NOT ABOUT THIS FILE?)" in text


def test_a_report_with_no_misses_says_every_label_passed() -> None:
    """Verify an agent with nothing below 100% gets a one-line report instead of label sections."""
    result = LabelResult(label=make_label(), highest_per_run=[Priority.MEDIUM], incidents_per_run=[[]])

    text = render_transcript_report(make_report([result]), LOG_NAME)

    assert "Every label passed on every run." in text
    assert "## clear-medium" not in text


def test_a_run_without_a_recorded_transcript_says_so() -> None:
    """Verify a report read from before transcripts existed does not crash and states what is missing."""
    result = LabelResult(label=make_label(), highest_per_run=[Priority.HIGH], incidents_per_run=[[]])

    assert "No transcript was recorded for this run." in render_transcript_report(make_report([result]), LOG_NAME)
