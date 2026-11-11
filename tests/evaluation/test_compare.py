"""
    Tests for comparing a report with a baseline: hand-built objects, no model.
"""
from code_reviewer.schemas.review import Priority
from evaluation.baselines import Baseline, LabelBaseline
from evaluation.compare import compare_agent, describe
from evaluation.labels import FixtureLabel
from evaluation.report_file import ReportFile
from evaluation.run_record import RunRecord
from evaluation.scoring import AgentScore, LabelResult


def make_result(label_id: str, correct: int, total: int = 5) -> LabelResult:
    label = FixtureLabel(id=label_id, fixture="shared/x.py", path="x.py", expected=Priority.HIGH, reason="built as high")
    return LabelResult(label=label, highest_per_run=[Priority.HIGH] * correct + [None] * (total - correct))


def make_baseline(rates: dict[str, float], runs: int = 5, pass_rate: float = 1.0) -> Baseline:
    score = AgentScore(
        agent="bound", labels=len(rates), failed_runs=0, abandoned_runs=0, invalid_line_incidents=0, pass_rate=pass_rate,
        recall=None, false_positive_rate=None, exact_priority_rate=None, accepted_priority_rate=None,
    )
    return Baseline(
        agent="bound", model="model-x", git_commit="abc1234", prompt_hash="old", prompt_hash_source="run_record",
        score=score, labels={label: LabelBaseline(accepted_rate=rate, runs=runs) for label, rate in rates.items()},
    )


def make_report(results: list[LabelResult], prompt_hash: str | None = None) -> ReportFile:
    record = RunRecord(git_commit="def5678", git_dirty=False, prompt_hash_by_agent={"bound": prompt_hash}) if prompt_hash else None
    return ReportFile(model_by_agent={"bound": "model-x"}, runs_per_label=5, run_record=record, results={"bound": results})


def test_a_drop_of_two_runs_is_reported_as_worse() -> None:
    """Verify losing two of five runs on a label is large enough to count as real."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 3)]))

    assert [change.label_id for change in comparison.worse] == ["a"]


def test_a_drop_of_one_run_is_noise() -> None:
    """Verify a single lost run out of five is not reported, since runs vary by chance."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 4)]))

    assert comparison.worse == []


def test_a_gain_of_two_runs_is_reported_as_better() -> None:
    """Verify improvements are reported with the same two-run rule."""
    comparison = compare_agent(make_baseline({"a": 0.6}), make_report([make_result("a", 5)]))

    assert [change.label_id for change in comparison.better] == ["a"]


def test_an_agent_that_drops_more_than_ten_points_regressed() -> None:
    """Verify the agent-level gate: pass rate down by over 10 points fails."""
    comparison = compare_agent(make_baseline({"a": 1.0}, pass_rate=1.0), make_report([make_result("a", 3)]))

    assert comparison.regressed


def test_an_agent_that_drops_exactly_ten_points_did_not_regress() -> None:
    """Verify the limit is strict, so a drop of exactly 10 points passes."""
    comparison = compare_agent(make_baseline({"a": 1.0}, pass_rate=0.9), make_report([make_result("a", 4)]))

    assert not comparison.regressed


def test_a_label_missing_from_the_baseline_is_left_out() -> None:
    """Verify a label added after the baseline was pinned does not break the comparison."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 5), make_result("new", 0)]))

    assert comparison.worse == []


def test_the_prompt_is_reported_changed_when_its_hash_differs() -> None:
    """Verify a run record with another prompt hash means the prompt was edited."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 5)], prompt_hash="new"))

    assert comparison.prompt_changed is True


def test_the_prompt_is_unchanged_when_its_hash_matches() -> None:
    """Verify an identical prompt hash is reported as unchanged."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 5)], prompt_hash="old"))

    assert comparison.prompt_changed is False


def test_a_report_without_a_run_record_cannot_say_whether_the_prompt_changed() -> None:
    """Verify an old report gives None, not a guess."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 5)]))

    assert comparison.prompt_changed is None


def test_a_different_model_is_reported_as_changed() -> None:
    """Verify a report from another model than the baseline's is flagged, since it explains a score change."""
    report = make_report([make_result("a", 5)])
    report.model_by_agent["bound"] = "model-y"

    assert compare_agent(make_baseline({"a": 1.0}), report).model_changed


def test_the_same_model_is_reported_unchanged() -> None:
    """Verify matching model names are not flagged."""
    assert not compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 5)])).model_changed


def test_the_printed_summary_names_the_verdict_and_the_worse_labels() -> None:
    """Verify the text a person reads says REGRESSED and which label dropped."""
    comparison = compare_agent(make_baseline({"a": 1.0}), make_report([make_result("a", 2)], prompt_hash="new"))

    text = "\n".join(describe(comparison))

    assert "REGRESSED" in text
    assert "a 100% -> 40%" in text
    assert "prompt: CHANGED" in text
