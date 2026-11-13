"""
    Tests for the calibration agreement scoring and the per-pair judge call, with a fake judge and no model.
"""
from pathlib import Path

import pytest

from code_reviewer.rag.dry_judge import DryJudgeInvocationError, JudgeCandidate
from code_reviewer.schemas.review import Incident, Priority
from evaluation.calibration.agreement import build_report, judge_pair, rescore_saved_report
from evaluation.calibration.agreement_scoring import (
    CalibrationSet,
    HumanLabel,
    IncompleteCalibrationError,
    PairJudgement,
    ensure_complete,
    find_disagreements,
    score_by_band,
)
from evaluation.calibration.make_pairs import CalibrationPair, PairSide


def _side(name: str) -> PairSide:
    return PairSide(file_path=f"api/{name}.py", chunk_name=name, start_line=1, end_line=9, code=f"def {name}(): ...")


def _pair(pair_id: str) -> CalibrationPair:
    return CalibrationPair(pair_id=pair_id, left=_side("left"), right=_side("right"))


def _calibration_set(rows: list[tuple[str, str, bool]]) -> CalibrationSet:
    return CalibrationSet(
        pairs=[_pair(pair_id) for pair_id, _, _ in rows],
        labels={pair_id: HumanLabel(pair_id=pair_id, is_duplicate=human, note=None) for pair_id, _, human in rows},
        bands={pair_id: band for pair_id, band, _ in rows},
    )


def _judgement(pair_id: str, judge_duplicate: bool | None) -> PairJudgement:
    failure = "boom" if judge_duplicate is None else None
    return PairJudgement(pair_id=pair_id, judge_duplicate=judge_duplicate, failure=failure, description=None)


class FakeJudge:
    def __init__(self, incidents: list[Incident] | None = None, error: Exception | None = None) -> None:
        self._incidents = incidents or []
        self._error = error
        self.calls: list[tuple[str, list[JudgeCandidate]]] = []

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        self.calls.append((query_code, candidates))
        if self._error is not None:
            raise self._error
        return self._incidents


def test_the_score_counts_each_outcome_per_band_and_overall() -> None:
    calibration_set = _calibration_set(
        [("a", "high", True), ("b", "high", False), ("c", "low", False), ("d", "low", True)]
    )
    judgements = [_judgement("a", True), _judgement("b", True), _judgement("c", False), _judgement("d", False)]

    scores = {score.band: score for score in score_by_band(judgements, calibration_set)}

    assert (scores["high"].true_positives, scores["high"].false_positives) == (1, 1)
    assert (scores["low"].true_negatives, scores["low"].false_negatives) == (1, 1)
    assert scores["overall"].judged == 4 and scores["overall"].accuracy == 0.5


def test_precision_and_recall_are_none_when_there_is_nothing_to_divide() -> None:
    calibration_set = _calibration_set([("a", "low", False)])

    score = score_by_band([_judgement("a", False)], calibration_set)[0]

    assert score.precision is None and score.recall is None and score.accuracy == 1.0


def test_a_failed_call_is_counted_apart_and_left_out_of_the_scores() -> None:
    calibration_set = _calibration_set([("a", "high", True), ("b", "high", True)])

    score = score_by_band([_judgement("a", True), _judgement("b", None)], calibration_set)[-1]

    assert score.failed == 1 and score.judged == 1 and score.recall == 1.0


def test_disagreements_list_only_judged_pairs_where_the_answers_differ() -> None:
    calibration_set = _calibration_set([("a", "high", True), ("b", "high", False), ("c", "low", True)])
    judgements = [_judgement("a", True), _judgement("b", True), _judgement("c", None)]

    found = find_disagreements(judgements, calibration_set)

    assert [item.pair_id for item in found] == ["b"] and found[0].human_duplicate is False


def test_pairs_labels_and_bands_must_name_the_same_pairs() -> None:
    calibration_set = _calibration_set([("a", "high", True)])
    calibration_set.labels.pop("a")

    with pytest.raises(IncompleteCalibrationError):
        ensure_complete(calibration_set)


def test_the_left_snippet_is_reviewed_against_the_right_one_as_the_only_candidate() -> None:
    judge = FakeJudge()

    judge_pair(judge, _pair("a"))

    query, candidates = judge.calls[0]
    assert query == "def left(): ..." and [c.code for c in candidates] == ["def right(): ..."]


def test_an_incident_means_the_judge_said_duplicate_and_keeps_its_description() -> None:
    incident = Incident(priority=Priority.MEDIUM, line_position="1-9", description="same loop", advice="extract")

    judgement = judge_pair(FakeJudge([incident]), _pair("a"))

    assert judgement.judge_duplicate is True and judgement.description == "same loop"


def test_no_incident_means_not_a_duplicate() -> None:
    assert judge_pair(FakeJudge(), _pair("a")).judge_duplicate is False


def test_a_judge_failure_is_recorded_not_raised() -> None:
    judgement = judge_pair(FakeJudge(error=DryJudgeInvocationError("timed out")), _pair("a"))

    assert judgement.judge_duplicate is None and judgement.failure == "timed out"


def test_a_failure_names_its_root_cause() -> None:
    try:
        raise DryJudgeInvocationError("judge failed") from TimeoutError("180s")
    except DryJudgeInvocationError as error:
        judgement = judge_pair(FakeJudge(error=error), _pair("a"))

    assert judgement.failure == "judge failed Cause: TimeoutError: 180s"


def test_a_saved_report_is_scored_again_against_the_labels_as_they_are_now(tmp_path: Path) -> None:
    calibration_set = _calibration_set([("a", "high", True), ("b", "low", False)])
    saved = build_report("some/model", [_judgement("a", False), _judgement("b", False)], calibration_set)
    path = tmp_path / "report.json"
    path.write_text(saved.model_dump_json())
    calibration_set.labels["a"] = HumanLabel(pair_id="a", is_duplicate=False, note=None)

    rescored = rescore_saved_report(path, calibration_set)

    assert saved.scores[-1].false_negatives == 1
    assert rescored.scores[-1].false_negatives == 0 and rescored.model == "some/model"
