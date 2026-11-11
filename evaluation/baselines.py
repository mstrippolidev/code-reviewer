"""
    The scores each agent is held to: the latest result per label from existing reports, pinned in a file.

        uv run python -m evaluation.baselines --agent bound evaluation/results/*/*/*-bound.json
"""
import argparse
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.openrouter import OpenRouter
from evaluation.report_file import ReportFile, read_report
from evaluation.reviewer import prompt_hash_for
from evaluation.scoring import AgentScore, score_agent
from evaluation.weak_labels import latest_results

BASELINES_FILE = Path(__file__).parent / "baselines.json"
UNKNOWN_COMMIT = "unknown"


class LabelBaseline(BaseModel):
    accepted_rate: float
    runs: int


class Baseline(BaseModel):
    agent: str
    model: str
    git_commit: str
    prompt_hash: str
    prompt_hash_source: Literal["run_record", "current_prompts"]
    score: AgentScore
    labels: dict[str, LabelBaseline]


BASELINES = TypeAdapter(dict[str, Baseline])


def load_baselines(path: Path = BASELINES_FILE) -> dict[str, Baseline]:
    """Every pinned baseline by agent; empty when nothing has been pinned yet."""
    if not path.exists():
        return {}
    return BASELINES.validate_json(path.read_text())


def save_baselines(baselines: dict[str, Baseline], path: Path = BASELINES_FILE) -> None:
    """Writes all baselines, sorted by agent so the file diffs cleanly."""
    ordered = dict(sorted(baselines.items()))
    path.write_bytes(BASELINES.dump_json(ordered, indent=2) + b"\n")


def baseline_from_reports(agent: str, report_paths: list[Path], llm: LLMInterface) -> Baseline:
    """Pin an agent's baseline from the latest result of each of its labels across the given reports."""
    results = [result for (name, _), result in latest_results(report_paths).items() if name == agent]
    newest = _newest_report_with(agent, report_paths)
    recorded_hash = newest.run_record.prompt_hash_by_agent.get(agent) if newest.run_record else None
    return Baseline(
        agent=agent,
        model=newest.model_by_agent[agent],
        git_commit=newest.run_record.git_commit if newest.run_record else UNKNOWN_COMMIT,
        prompt_hash=recorded_hash or prompt_hash_for(agent, llm),
        prompt_hash_source="run_record" if recorded_hash else "current_prompts",
        score=score_agent(agent, results),
        labels={result.label.id: LabelBaseline(accepted_rate=result.accepted_rate, runs=result.total_runs) for result in results},
    )


def _newest_report_with(agent: str, report_paths: list[Path]) -> ReportFile:
    """The most recent report that holds results for the agent; raises when none does."""
    for path in sorted(report_paths, key=lambda report: report.name, reverse=True):
        report = read_report(path)
        if agent in report.results:
            return report
    raise ValueError(f"none of the given reports holds results for '{agent}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pin agents' baselines from existing evaluation reports.")
    parser.add_argument("--agent", action="append", required=True, help="an agent to pin; repeat for several")
    parser.add_argument("reports", nargs="+", type=Path, help="reports to take the latest result per label from")
    arguments = parser.parse_args()
    llm = OpenRouter()
    baselines = load_baselines()
    for agent in arguments.agent:
        baselines[agent] = baseline_from_reports(agent, arguments.reports, llm)
        print(f"{agent}: pass {baselines[agent].score.pass_rate:.0%} over {len(baselines[agent].labels)} labels")
    save_baselines(baselines)


if __name__ == "__main__":
    main()
