"""
    Tests for choosing the labels to run again from earlier report files: reports written to a temp folder, no model.
"""
from datetime import datetime, timezone
from pathlib import Path

from code_reviewer.schemas.review import Priority
from evaluation.labels import FixtureLabel
from evaluation.scoring import EvaluationReport, LabelResult, score_agent
from evaluation.weak_labels import weak_label_ids


def label(label_id: str) -> FixtureLabel:
    return FixtureLabel(id=label_id, fixture="shared/x.py", path="x.py", expected=Priority.HIGH, reason="test")


def write_report(path: Path, agent: str, results: list[LabelResult]) -> Path:
    report = EvaluationReport(
        model_by_agent={agent: "model"},
        runs_per_label=2,
        created_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        scores=[score_agent(agent, results)],
        results={agent: results},
    )
    path.write_text(report.model_dump_json())
    return path


def test_only_labels_that_missed_a_run_are_returned(tmp_path: Path) -> None:
    """Verify a label that passed every run is left out and one that missed is listed under its agent."""
    results = [
        LabelResult(label=label("always"), highest_per_run=[Priority.HIGH, Priority.HIGH]),
        LabelResult(label=label("sometimes"), highest_per_run=[Priority.HIGH, Priority.LOW]),
    ]
    path = write_report(tmp_path / "20261107-000000-bound.json", "bound", results)

    assert weak_label_ids([path]) == {"bound": ["sometimes"]}


def test_a_later_report_replaces_an_earlier_result_for_the_same_label(tmp_path: Path) -> None:
    """Verify a recheck that passed removes a label an earlier full run had marked weak."""
    weak = LabelResult(label=label("flaky"), highest_per_run=[Priority.LOW, Priority.LOW])
    fixed = LabelResult(label=label("flaky"), highest_per_run=[Priority.HIGH, Priority.HIGH])
    earlier = write_report(tmp_path / "20261107-000000-bound.json", "bound", [weak])
    later = write_report(tmp_path / "20261109-000000-bound.json", "bound", [fixed])

    assert weak_label_ids([later, earlier]) == {}
