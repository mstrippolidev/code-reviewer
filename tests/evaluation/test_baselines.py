"""
    Tests for pinning baselines from saved reports: hand-built report files, no model.
"""
from pathlib import Path

import pytest

from code_reviewer.schemas.review import Priority
from evaluation import baselines
from evaluation.baselines import baseline_from_reports, load_baselines, save_baselines
from evaluation.labels import FixtureLabel
from evaluation.report_file import ReportFile
from evaluation.run_record import RunRecord
from evaluation.scoring import LabelResult


def make_result(label_id: str, answers: list[Priority | None]) -> LabelResult:
    label = FixtureLabel(id=label_id, fixture="shared/x.py", path="x.py", expected=Priority.HIGH, reason="built as high")
    return LabelResult(label=label, highest_per_run=answers)


def write_report(path: Path, results: list[LabelResult], run_record: RunRecord | None = None) -> Path:
    report = ReportFile(model_by_agent={"bound": "model-x"}, runs_per_label=5, run_record=run_record, results={"bound": results})
    path.write_text(report.model_dump_json())
    return path


@pytest.fixture(autouse=True)
def fixed_current_prompt_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(baselines, "prompt_hash_for", lambda agent, llm: "current-hash")


def test_a_later_report_replaces_the_result_of_the_same_label(tmp_path: Path) -> None:
    """Verify a rerun of one label updates the baseline while the other labels keep their earlier result."""
    first = write_report(
        tmp_path / "20261107-000000-bound.json",
        [make_result("a", [Priority.HIGH] * 5), make_result("b", [Priority.HIGH, None, None, None, None])],
    )
    rerun = write_report(tmp_path / "20261110-000000-bound.json", [make_result("b", [Priority.HIGH] * 5)])

    baseline = baseline_from_reports("bound", [first, rerun], llm=None)

    assert {label: pinned.accepted_rate for label, pinned in baseline.labels.items()} == {"a": 1.0, "b": 1.0}
    assert baseline.score.pass_rate == 1.0


def test_the_score_is_recomputed_from_the_merged_results(tmp_path: Path) -> None:
    """Verify the pinned pass rate is the mean over labels, not a number copied from one report."""
    report = write_report(
        tmp_path / "20261110-000000-bound.json",
        [make_result("a", [Priority.HIGH] * 5), make_result("b", [None] * 5)],
    )

    assert baseline_from_reports("bound", [report], llm=None).score.pass_rate == 0.5


def test_an_old_report_takes_the_hash_of_the_current_prompt(tmp_path: Path) -> None:
    """Verify a report without a run record is pinned with today's prompt hash and says so."""
    report = write_report(tmp_path / "20261107-000000-bound.json", [make_result("a", [Priority.HIGH] * 5)])

    baseline = baseline_from_reports("bound", [report], llm=None)

    assert (baseline.prompt_hash, baseline.prompt_hash_source, baseline.git_commit) == ("current-hash", "current_prompts", "unknown")


def test_a_report_with_a_run_record_keeps_its_own_hash(tmp_path: Path) -> None:
    """Verify the hash recorded at run time wins over the current prompt."""
    record = RunRecord(git_commit="abc1234", git_dirty=False, prompt_hash_by_agent={"bound": "recorded-hash"})
    report = write_report(tmp_path / "20261110-000000-bound.json", [make_result("a", [Priority.HIGH] * 5)], record)

    baseline = baseline_from_reports("bound", [report], llm=None)

    assert (baseline.prompt_hash, baseline.prompt_hash_source, baseline.git_commit) == ("recorded-hash", "run_record", "abc1234")


def test_an_agent_missing_from_every_report_raises(tmp_path: Path) -> None:
    """Verify pinning an agent that no report covers fails instead of writing an empty baseline."""
    report = write_report(tmp_path / "20261110-000000-bound.json", [make_result("a", [Priority.HIGH] * 5)])

    with pytest.raises(ValueError):
        baseline_from_reports("tcase", [report], llm=None)


def test_baselines_survive_a_save_and_load(tmp_path: Path) -> None:
    """Verify the pinned file round-trips and a missing file loads as empty."""
    report = write_report(tmp_path / "20261110-000000-bound.json", [make_result("a", [Priority.HIGH] * 5)])
    pinned = baseline_from_reports("bound", [report], llm=None)
    target = tmp_path / "baselines.json"

    assert load_baselines(target) == {}
    save_baselines({"bound": pinned}, target)

    assert load_baselines(target) == {"bound": pinned}
