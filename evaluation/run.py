"""
    Runs labelled fixtures through real agents on OpenRouter, several times
    each, and scores the answers against their labels.

        uv run python -m evaluation.run --agent naming --runs 5
        uv run python -m evaluation.run --agent naming --only clear-high-priority-fixture --runs 2
        uv run python -m evaluation.run --below-full-pass evaluation/results/*/2026-11-07/*.json

    Files go to evaluation/results/<model>/<day>/ (scores, transcripts) and
    evaluation/results/<model>/logs/ (the model's reasoning).
"""
import argparse
import os
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.schemas.review import Incident, Priority
from evaluation.incidents import highest_priority
from evaluation.labels import FixtureLabel, label_folders, load_labels
from evaluation.result_paths import REASONING_LOG_SUFFIX, result_files
from evaluation.reviewer import LabelReviewer, production_llm_for, prompt_hash_for
from evaluation.run_record import build_run_record
from evaluation.scoring import AgentScore, EvaluationReport, LabelResult, score_agent
from evaluation.transcript import RunTranscript
from evaluation.transcript_report import render_reasoning_log, render_transcript_report
from evaluation.weak_labels import weak_label_ids

RESULTS_DIR = Path(__file__).parent / "results"


class RunOptions(BaseModel):
    agents: list[str]
    runs: int
    workers: int
    only_by_agent: dict[str, list[str]]
    model: str | None
    deadline_minutes: float | None


def parse_options(arguments: list[str]) -> RunOptions:
    """Read the command line into validated options."""
    parser = argparse.ArgumentParser(description="Score agents against their labelled fixtures.")
    parser.add_argument("--agent", nargs="+", default=[], choices=label_folders(), help="fixture folders to run")
    parser.add_argument("--runs", type=int, default=5, help="times each fixture is run")
    parser.add_argument("--workers", type=int, default=4, help="model calls in flight at once")
    parser.add_argument("--only", nargs="+", default=[], help="label ids to run, instead of all of an agent's")
    parser.add_argument(
        "--below-full-pass",
        nargs="+",
        type=Path,
        default=[],
        help="earlier report files: run only the labels that did not pass every run in them",
    )
    parser.add_argument("--model", default=None, help="OpenRouter model id, instead of OPENROUTER_MODEL")
    parser.add_argument(
        "--deadline-minutes", type=float, default=None, help="per agent: stop waiting after this long and save what finished"
    )
    parsed = parser.parse_args(arguments)
    if parsed.runs < 1 or parsed.workers < 1:
        parser.error("--runs and --workers must be at least 1")
    if not parsed.agent and not parsed.below_full_pass:
        parser.error("give --agent, --below-full-pass, or both")
    only_by_agent = labels_to_run(parsed.agent, parsed.only, parsed.below_full_pass)
    return RunOptions(
        agents=list(only_by_agent),
        runs=parsed.runs,
        workers=parsed.workers,
        only_by_agent=only_by_agent,
        model=parsed.model,
        deadline_minutes=parsed.deadline_minutes,
    )


def labels_to_run(agents: list[str], only: list[str], report_paths: list[Path]) -> dict[str, list[str]]:
    """Label ids per agent; an empty list means all of that agent's labels."""
    if not report_paths:
        return {agent: only for agent in agents}
    weak = weak_label_ids(report_paths)
    return {agent: ids for agent, ids in weak.items() if not agents or agent in agents}


def select_labels(folder: str, only: list[str]) -> list[FixtureLabel]:
    """The agent's labels, narrowed to the requested ids when any were given."""
    labels = load_labels(folder)
    if not only:
        return labels
    wanted = [label for label in labels if label.id in only]
    if not wanted:
        raise ValueError(f"none of {only} is a label id of '{folder}'")
    return wanted


def collect_label_result(label: FixtureLabel, futures: list[Future], deadline: float | None) -> LabelResult:
    """Wait for one label's runs until the deadline; a run that raised is failed, one still pending is abandoned."""
    remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
    _, not_finished = wait(futures, timeout=remaining)
    highest_per_run: list[Priority | None] = []
    incidents_per_run: list[list[Incident]] = []
    transcripts_per_run: list[RunTranscript] = []
    invalid_lines_per_run: list[int] = []
    failures: list[str] = []
    for future in futures:
        if future in not_finished:
            future.cancel()
            continue
        try:
            run = future.result()
        except Exception as error:
            failures.append(f"{type(error).__name__}: {error}")
            print(f"  run failed on {label.id}: {failures[-1]}", file=sys.stderr)
            continue
        highest_per_run.append(highest_priority(run.entry))
        incidents_per_run.append(run.entry.incidents)
        transcripts_per_run.append(run.transcript)
        invalid_lines_per_run.append(run.invalid_line_incidents)
    return LabelResult(
        label=label,
        highest_per_run=highest_per_run,
        incidents_per_run=incidents_per_run,
        transcripts_per_run=transcripts_per_run,
        failed_runs=len(failures),
        abandoned_runs=len(not_finished),
        invalid_line_incidents=sum(invalid_lines_per_run),
        invalid_lines_per_run=invalid_lines_per_run,
        failures=failures,
    )


def evaluate_agent(folder: str, options: RunOptions, llm: LLMInterface) -> list[LabelResult]:
    """Run every selected label of one agent options.runs times and gather the results."""
    reviewer = LabelReviewer(folder, llm)
    labels = select_labels(folder, options.only_by_agent[folder])
    deadline = None if options.deadline_minutes is None else time.monotonic() + options.deadline_minutes * 60
    pool = ThreadPoolExecutor(max_workers=options.workers)
    submitted = [(label, [pool.submit(reviewer.review_run, label) for _ in range(options.runs)]) for label in labels]
    results = [collect_label_result(label, futures, deadline) for label, futures in submitted]
    pool.shutdown(wait=False, cancel_futures=True)
    return results


def build_report(options: RunOptions, results: dict[str, list[LabelResult]], llm: LLMInterface) -> EvaluationReport:
    """Score every agent and stamp the report with the model, prompt and code each agent actually ran on."""
    prompt_hashes = {folder: prompt_hash_for(folder, llm) for folder in results}
    return EvaluationReport(
        model_by_agent={folder: production_llm_for(folder, llm).model_name for folder in results},
        runs_per_label=options.runs,
        created_at=datetime.now(timezone.utc),
        run_record=build_run_record(prompt_hashes),
        scores=[score_agent(folder, folder_results) for folder, folder_results in results.items()],
        results=results,
    )


def print_models(model_by_agent: dict[str, str]) -> None:
    """Show the model each agent ran on, the way production routes it."""
    for folder, model in model_by_agent.items():
        print(f"{folder} ran on {model}")


def format_rate(rate: float | None) -> str:
    return "  n/a" if rate is None else f"{rate:5.0%}"


def print_scores(scores: list[AgentScore]) -> None:
    """One line per agent: how often it passes, catches violations, and cries wolf."""
    print(
        f"{'agent':<12}{'labels':>7}{'failed':>7}{'cutoff':>7}{'badline':>8}{'pass':>7}{'recall':>8}{'false+':>8}{'exact':>8}{'accepted':>10}"
    )
    for score in scores:
        print(
            f"{score.agent:<12}{score.labels:>7}{score.failed_runs:>7}{score.abandoned_runs:>7}"
            f"{score.invalid_line_incidents:>8}{format_rate(score.pass_rate):>7}"
            f"{format_rate(score.recall):>8}{format_rate(score.false_positive_rate):>8}"
            f"{format_rate(score.exact_priority_rate):>8}{format_rate(score.accepted_priority_rate):>10}"
        )


def print_unaccepted_runs(result: LabelResult) -> None:
    """Show what the agent actually reported on each run the label did not accept."""
    for highest, incidents in zip(result.highest_per_run, result.incidents_per_run):
        if highest in result.label.accepted:
            continue
        print(f"    run answered {highest.value if highest else 'none'}:")
        for incident in incidents:
            print(f"      [{incident.priority.value}] {incident.line_position}: {incident.description}")


def print_labels_below_full_pass(results: dict[str, list[LabelResult]]) -> None:
    """List the labels that did not pass on every run, with the incidents of each run that missed."""
    for folder, folder_results in results.items():
        for result in folder_results:
            if result.accepted_rate < 1:
                answers = [highest.value if highest else "none" for highest in result.highest_per_run]
                print(f"  {folder}/{result.label.id}: passed {result.accepted_rate:.0%}, answers {answers}")
                print_unaccepted_runs(result)


def report_of_agent(report: EvaluationReport, folder: str) -> EvaluationReport:
    """The part of a multi-agent report that belongs to one agent."""
    return EvaluationReport(
        model_by_agent={folder: report.model_by_agent[folder]},
        runs_per_label=report.runs_per_label,
        created_at=report.created_at,
        run_record=report.run_record.only(folder) if report.run_record else None,
        scores=[score for score in report.scores if score.agent == folder],
        results={folder: report.results[folder]},
    )


def write_agent_files(report: EvaluationReport, folder: str) -> list[Path]:
    """Save one agent's scores and transcripts as JSON, its missed-label transcripts as markdown, and their reasoning as a log."""
    agent_report = report_of_agent(report, folder)
    files = result_files(RESULTS_DIR, report.model_by_agent[folder], report.created_at, folder)
    for path in (files.scores, files.transcripts, files.reasoning_log):
        path.parent.mkdir(parents=True, exist_ok=True)
    files.scores.write_text(agent_report.model_dump_json(indent=2))
    files.transcripts.write_text(render_transcript_report(agent_report, files.reasoning_log.name))
    files.reasoning_log.write_text(render_reasoning_log(agent_report))
    return [files.scores, files.transcripts, files.reasoning_log]


def main() -> None:
    options = parse_options(sys.argv[1:])
    llm = OpenRouter(model_name=options.model)
    results: dict[str, list[LabelResult]] = {}
    for folder in options.agents:
        print(f"running {folder} ...", file=sys.stderr)
        results[folder] = evaluate_agent(folder, options, llm)
    report = build_report(options, results, llm)
    print_models(report.model_by_agent)
    print_scores(report.scores)
    print_labels_below_full_pass(results)
    for folder in options.agents:
        for path in write_agent_files(report, folder):
            kind = "reasoning log" if path.name.endswith(REASONING_LOG_SUFFIX) else "report"
            print(f"{kind}: {path}")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
