"""
    Compares a new evaluation report with the pinned baseline of each agent in it, and exits 1 when an agent
    got worse.

        uv run python -m evaluation.compare evaluation/results/<model>/<day>/<report>.json
"""
import argparse
from pathlib import Path

from pydantic import BaseModel

from evaluation.baselines import Baseline, load_baselines
from evaluation.labels import LabelKind
from evaluation.report_file import ReportFile, read_report
from evaluation.scoring import LabelResult, score_agent

AGENT_DROP_LIMIT = 0.10
MIN_RUNS_CHANGED = 2


class LabelChange(BaseModel):
    label_id: str
    before: float
    after: float


class Comparison(BaseModel):
    agent: str
    pass_rate_before: float
    pass_rate_after: float
    pass_rate_by_kind_after: dict[LabelKind, float] = {}
    prompt_changed: bool | None
    model_changed: bool
    worse: list[LabelChange]
    better: list[LabelChange]

    @property
    def regressed(self) -> bool:
        """True when the agent's pass rate fell by more than the allowed drop."""
        return self.pass_rate_before - self.pass_rate_after > AGENT_DROP_LIMIT


def compare_agent(baseline: Baseline, report: ReportFile) -> Comparison:
    """How one agent's new results differ from its baseline, ignoring changes within run-to-run noise."""
    results = report.results[baseline.agent]
    changes = [_change_of(baseline, result) for result in results if result.label.id in baseline.labels]
    real = [change for change in changes if _is_real(change, baseline, report)]
    score = score_agent(baseline.agent, results)
    return Comparison(
        agent=baseline.agent,
        pass_rate_before=baseline.score.pass_rate,
        pass_rate_after=score.pass_rate,
        pass_rate_by_kind_after=score.pass_rate_by_kind,
        prompt_changed=_prompt_changed(baseline, report),
        model_changed=report.model_by_agent[baseline.agent] != baseline.model,
        worse=[change for change in real if change.after < change.before],
        better=[change for change in real if change.after > change.before],
    )


def _change_of(baseline: Baseline, result: LabelResult) -> LabelChange:
    return LabelChange(
        label_id=result.label.id,
        before=baseline.labels[result.label.id].accepted_rate,
        after=result.accepted_rate,
    )


def _is_real(change: LabelChange, baseline: Baseline, report: ReportFile) -> bool:
    """A change counts when it is worth at least MIN_RUNS_CHANGED runs of the smaller sample."""
    runs = min(baseline.labels[change.label_id].runs, report.runs_per_label)
    return abs(change.after - change.before) * runs >= MIN_RUNS_CHANGED


def _prompt_changed(baseline: Baseline, report: ReportFile) -> bool | None:
    """None when the new report has no run record, so the question cannot be answered."""
    if report.run_record is None:
        return None
    return report.run_record.prompt_hash_by_agent.get(baseline.agent) != baseline.prompt_hash


def describe(comparison: Comparison) -> list[str]:
    """The lines printed for one agent."""
    verdict = "REGRESSED" if comparison.regressed else "OK"
    prompt = {None: "unknown", True: "CHANGED", False: "unchanged"}[comparison.prompt_changed]
    lines = [
        f"{comparison.agent:<12}pass {comparison.pass_rate_before:.0%} -> {comparison.pass_rate_after:.0%}"
        f"   prompt: {prompt}   model: {'CHANGED' if comparison.model_changed else 'unchanged'}   {verdict}"
    ]
    if set(comparison.pass_rate_by_kind_after) - {LabelKind.STANDARD}:
        by_kind = ", ".join(f"{kind.value} {rate:.0%}" for kind, rate in comparison.pass_rate_by_kind_after.items())
        lines.append(f"  by kind: {by_kind}")
    lines.append("  worse : " + (_changes_text(comparison.worse) or "none"))
    lines.append("  better: " + (_changes_text(comparison.better) or "none"))
    return lines


def _changes_text(changes: list[LabelChange]) -> str:
    return ", ".join(f"{change.label_id} {change.before:.0%} -> {change.after:.0%}" for change in changes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a report with the pinned baselines.")
    parser.add_argument("report", type=Path)
    arguments = parser.parse_args()
    report = read_report(arguments.report)
    baselines = load_baselines()
    regressed = False
    for agent in report.results:
        if agent not in baselines:
            print(f"{agent:<12}no baseline pinned")
            continue
        comparison = compare_agent(baselines[agent], report)
        print("\n".join(describe(comparison)))
        regressed = regressed or comparison.regressed
    if regressed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
