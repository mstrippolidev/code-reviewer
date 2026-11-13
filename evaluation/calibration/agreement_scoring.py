"""
    Scores a judge's duplicate verdicts against human labels, overall and per similarity band.
"""
from pydantic import BaseModel, computed_field

from evaluation.calibration.make_pairs import CalibrationPair

OVERALL_BAND = "overall"
BAND_ORDER = ("high", "middle", "low")


class IncompleteCalibrationError(Exception):
    """Raised when pairs, labels and bands do not cover the same pair ids."""


class HumanLabel(BaseModel):
    pair_id: str
    is_duplicate: bool
    note: str | None


class CalibrationSet(BaseModel):
    pairs: list[CalibrationPair]
    labels: dict[str, HumanLabel]
    bands: dict[str, str]


class PairJudgement(BaseModel):
    pair_id: str
    judge_duplicate: bool | None
    failure: str | None
    description: str | None


class BandScore(BaseModel):
    band: str
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    failed: int

    @computed_field
    @property
    def judged(self) -> int:
        return self.true_positives + self.false_positives + self.false_negatives + self.true_negatives

    @computed_field
    @property
    def accuracy(self) -> float | None:
        return _ratio(self.true_positives + self.true_negatives, self.judged)

    @computed_field
    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_positives)

    @computed_field
    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positives, self.true_positives + self.false_negatives)


class Disagreement(BaseModel):
    pair_id: str
    band: str
    human_duplicate: bool
    human_note: str | None
    judge_description: str | None


def ensure_complete(calibration_set: CalibrationSet) -> None:
    """Raises if any pair lacks a human label or a band.

    Raises:
        IncompleteCalibrationError: If the three sources do not name the same pairs.
    """
    pair_ids = {pair.pair_id for pair in calibration_set.pairs}
    if pair_ids != set(calibration_set.labels) or pair_ids != set(calibration_set.bands):
        raise IncompleteCalibrationError("pairs, labels and bands must name exactly the same pair ids")


def score_by_band(judgements: list[PairJudgement], calibration_set: CalibrationSet) -> list[BandScore]:
    """One score per band that has pairs, in high-middle-low order, then the overall row."""
    bands = [band for band in BAND_ORDER if band in set(calibration_set.bands.values())]
    scores = [_score_band(band, judgements, calibration_set) for band in bands]
    return [*scores, _score_band(OVERALL_BAND, judgements, calibration_set)]


def find_disagreements(judgements: list[PairJudgement], calibration_set: CalibrationSet) -> list[Disagreement]:
    """Every judged pair where the judge and the human answered differently."""
    found = []
    for judgement in judgements:
        label = calibration_set.labels[judgement.pair_id]
        if judgement.judge_duplicate is not None and judgement.judge_duplicate != label.is_duplicate:
            found.append(
                Disagreement(
                    pair_id=judgement.pair_id,
                    band=calibration_set.bands[judgement.pair_id],
                    human_duplicate=label.is_duplicate,
                    human_note=label.note,
                    judge_description=judgement.description,
                )
            )
    return found


def _score_band(band: str, judgements: list[PairJudgement], calibration_set: CalibrationSet) -> BandScore:
    in_band = [
        judgement
        for judgement in judgements
        if band == OVERALL_BAND or calibration_set.bands[judgement.pair_id] == band
    ]
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    failed = 0
    for judgement in in_band:
        if judgement.judge_duplicate is None:
            failed += 1
            continue
        human = calibration_set.labels[judgement.pair_id].is_duplicate
        counts[_outcome(human, judgement.judge_duplicate)] += 1
    return BandScore(
        band=band,
        true_positives=counts["tp"],
        false_positives=counts["fp"],
        false_negatives=counts["fn"],
        true_negatives=counts["tn"],
        failed=failed,
    )


def _outcome(human_duplicate: bool, judge_duplicate: bool) -> str:
    if judge_duplicate:
        return "tp" if human_duplicate else "fp"
    return "fn" if human_duplicate else "tn"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None
