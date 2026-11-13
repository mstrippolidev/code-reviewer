"""
    Runs DryJudge once per labelled calibration pair on OpenRouter and reports how often it agrees with the human labels.
"""
import argparse
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.dry_judge import DryJudge, DryJudgeInvocationError, DryJudgeLike, JudgeCandidate, format_location
from code_reviewer.rag.dry_judge_split import SizeGuardedDryJudge, SplitConfig
from code_reviewer.schemas.review import CodeKey
from evaluation.calibration.agreement_scoring import (
    BandScore,
    CalibrationSet,
    Disagreement,
    HumanLabel,
    PairJudgement,
    ensure_complete,
    find_disagreements,
    score_by_band,
)
from evaluation.calibration.make_pairs import CalibrationPair, PairMeta
from evaluation.result_paths import folder_name_of

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FOLDER = REPO_ROOT / "tests" / "fixtures" / "dry_calibration"
RESULTS_FOLDER = REPO_ROOT / "evaluation" / "results" / "dry_calibration"
HUMAN_LABELS_FILE = "human_labels.json"


class AgreementReport(BaseModel):
    model: str
    created_at: str
    pairs_judged: int
    scores: list[BandScore]
    disagreements: list[Disagreement]
    judgements: list[PairJudgement]


def load_calibration_set(folder: Path) -> CalibrationSet:
    """Reads pairs.json, human_labels.json and pairs_meta.json from one folder.

    Raises:
        IncompleteCalibrationError: If they do not name the same pairs.
    """
    pairs = [CalibrationPair.model_validate(entry) for entry in json.loads((folder / "pairs.json").read_text())]
    labels = [HumanLabel.model_validate(entry) for entry in json.loads((folder / HUMAN_LABELS_FILE).read_text())]
    metas = [PairMeta.model_validate(entry) for entry in json.loads((folder / "pairs_meta.json").read_text())]
    calibration_set = CalibrationSet(
        pairs=pairs,
        labels={label.pair_id: label for label in labels},
        bands={meta.pair_id: meta.band for meta in metas},
    )
    ensure_complete(calibration_set)
    return calibration_set


def build_judge(llm: LLMInterface) -> DryJudgeLike:
    """The judge exactly as production wires it: the DRY model for this provider, wrapped in the size guard."""
    settings = get_settings()
    return SizeGuardedDryJudge(
        DryJudge(llm.for_code_key(CodeKey.DRY)),
        SplitConfig(
            max_pair_chars=settings.dry_judge_max_pair_chars, overlap_chars=settings.dry_judge_split_overlap_chars
        ),
    )


def judge_pair(judge: DryJudgeLike, pair: CalibrationPair) -> PairJudgement:
    """One judge call with the left snippet under review and the right one as the only candidate."""
    candidate = JudgeCandidate(location=format_location(pair.right), code=pair.right.code)
    try:
        incidents = judge.judge(pair.left.code, [candidate])
    except DryJudgeInvocationError as error:
        failure = describe_failure(error)
        return PairJudgement(pair_id=pair.pair_id, judge_duplicate=None, failure=failure, description=None)
    description = incidents[0].description if incidents else None
    return PairJudgement(pair_id=pair.pair_id, judge_duplicate=bool(incidents), failure=None, description=description)


def describe_failure(error: BaseException) -> str:
    """The failure with its root cause named, since the judge's own message only says that it failed."""
    root = error
    while root.__cause__ is not None:
        root = root.__cause__
    if root is error:
        return str(error)
    return f"{error} Cause: {type(root).__name__}: {root}"[:400]


def judge_all(judge: DryJudgeLike, pairs: list[CalibrationPair], workers: int, deadline_minutes: float) -> list[PairJudgement]:
    """Judges every pair in parallel; a pair still unfinished at the deadline is recorded as failed."""
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [(pair, pool.submit(judge_pair, judge, pair)) for pair in pairs]
    wait([future for _, future in futures], timeout=deadline_minutes * 60)
    pool.shutdown(wait=False, cancel_futures=True)
    return [_result_of(pair, future) for pair, future in futures]


def build_report(model: str, judgements: list[PairJudgement], calibration_set: CalibrationSet) -> AgreementReport:
    """Scores and disagreements for the judged pairs."""
    return AgreementReport(
        model=model,
        created_at=datetime.now().isoformat(timespec="seconds"),
        pairs_judged=sum(judgement.judge_duplicate is not None for judgement in judgements),
        scores=score_by_band(judgements, calibration_set),
        disagreements=find_disagreements(judgements, calibration_set),
        judgements=judgements,
    )


def render_table(report: AgreementReport) -> str:
    """The per-band scores as a plain text table."""
    header = f"{'band':<9}{'judged':>7}{'TP':>4}{'FP':>4}{'FN':>4}{'TN':>4}{'fail':>5}{'accuracy':>10}{'precision':>11}{'recall':>8}"
    rows = [
        f"{s.band:<9}{s.judged:>7}{s.true_positives:>4}{s.false_positives:>4}{s.false_negatives:>4}"
        f"{s.true_negatives:>4}{s.failed:>5}{_show(s.accuracy):>10}{_show(s.precision):>11}{_show(s.recall):>8}"
        for s in report.scores
    ]
    return "\n".join([header, *rows])


def write_report(report: AgreementReport, results_folder: Path) -> Path:
    """Saves the report under a folder per model and returns its path."""
    folder = results_folder / folder_name_of(report.model)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report.created_at.replace(':', '')}.json"
    path.write_text(report.model_dump_json(indent=2) + "\n")
    return path


def _result_of(pair: CalibrationPair, future: Future) -> PairJudgement:
    if not future.done():
        return PairJudgement(pair_id=pair.pair_id, judge_duplicate=None, failure="deadline reached", description=None)
    return future.result()


def _show(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare DryJudge with the human calibration labels.")
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N pairs, to try it cheaply")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--deadline-minutes", type=float, default=15.0)
    parser.add_argument("--model", default=None, help="OpenRouter model id, instead of OPENROUTER_MODEL")
    parser.add_argument(
        "--from-report", type=Path, default=None, help="score a saved report's verdicts against the current labels, with no model calls"
    )
    return parser.parse_args()


def rescore_saved_report(report_path: Path, calibration_set: CalibrationSet) -> AgreementReport:
    """The saved report's judgements scored again against the labels as they are now."""
    saved = AgreementReport.model_validate_json(report_path.read_text())
    return build_report(saved.model, saved.judgements, calibration_set)


def main() -> None:
    """Command line entry point: judges the pairs, prints the table and saves the report."""
    arguments = _parse_arguments()
    calibration_set = load_calibration_set(arguments.folder)
    if arguments.from_report is not None:
        report = rescore_saved_report(arguments.from_report, calibration_set)
        print(render_table(report))
        print(f"rescored without model calls, saved to {write_report(report, RESULTS_FOLDER)}")
        return
    pairs = calibration_set.pairs[: arguments.limit]
    llm = OpenRouter(model_name=arguments.model)
    judge = build_judge(llm)
    started = time.monotonic()
    judgements = judge_all(judge, pairs, arguments.workers, arguments.deadline_minutes)
    report = build_report(llm.for_code_key(CodeKey.DRY).model_name, judgements, calibration_set)
    print(render_table(report))
    print(f"{len(pairs)} pairs in {time.monotonic() - started:.0f}s, saved to {write_report(report, RESULTS_FOLDER)}")


if __name__ == "__main__":
    main()
