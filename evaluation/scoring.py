"""
    Turns repeated runs of labelled fixtures into the scores an agent is
    judged by. A run that raised counts against the agent: it produced no
    accepted answer.
"""
from datetime import datetime
from statistics import mean

from pydantic import BaseModel, computed_field

from code_reviewer.schemas.review import Incident, Priority
from evaluation.labels import FixtureLabel
from evaluation.run_record import RunRecord
from evaluation.transcript import RunTranscript


class LabelResult(BaseModel):
    label: FixtureLabel
    highest_per_run: list[Priority | None]
    incidents_per_run: list[list[Incident]] = []
    transcripts_per_run: list[RunTranscript] = []
    failed_runs: int = 0
    abandoned_runs: int = 0
    invalid_line_incidents: int = 0
    invalid_lines_per_run: list[int] = []
    failures: list[str] = []

    @property
    def total_runs(self) -> int:
        return len(self.highest_per_run) + self.failed_runs + self.abandoned_runs

    @computed_field
    @property
    def accepted_rate(self) -> float:
        """Share of runs whose most severe incident the label accepts."""
        accepted = sum(1 for highest in self.highest_per_run if highest in self.label.accepted)
        return accepted / self.total_runs

    @computed_field
    @property
    def rejected_rate(self) -> float:
        """Share of runs that answered, but with a severity the label does not accept."""
        rejected = sum(1 for highest in self.highest_per_run if highest not in self.label.accepted)
        return rejected / self.total_runs

    @computed_field
    @property
    def exact_rate(self) -> float:
        """Share of runs whose most severe incident is exactly the label's ideal answer."""
        exact = sum(1 for highest in self.highest_per_run if highest == self.label.expected)
        return exact / self.total_runs

    @computed_field
    @property
    def flagged_rate(self) -> float:
        """Share of runs that reported at least one incident."""
        flagged = sum(1 for highest in self.highest_per_run if highest is not None)
        return flagged / self.total_runs


class AgentScore(BaseModel):
    agent: str
    labels: int
    failed_runs: int
    abandoned_runs: int
    invalid_line_incidents: int
    pass_rate: float
    recall: float | None
    false_positive_rate: float | None
    exact_priority_rate: float | None
    accepted_priority_rate: float | None


class EvaluationReport(BaseModel):
    model_by_agent: dict[str, str]
    runs_per_label: int
    created_at: datetime
    run_record: RunRecord | None = None
    scores: list[AgentScore]
    results: dict[str, list[LabelResult]]


def _mean_or_none(rates: list[float]) -> float | None:
    """None only when the run held no label of that kind, so there is nothing to average."""
    return mean(rates) if rates else None


def score_agent(agent: str, results: list[LabelResult]) -> AgentScore:
    """Score one agent over its labelled fixtures.

    recall is the flagged rate over fixtures that have a violation;
    false_positive_rate is the rejected rate over fixtures labelled clean
    (a run that raised is a failed run, not a false alarm);
    the priority rates look only at fixtures with a specific expected priority.
    """
    violations = [result for result in results if not result.label.is_clean]
    clean = [result for result in results if result.label.is_clean]
    with_priority = [result for result in results if result.label.expected is not None]
    return AgentScore(
        agent=agent,
        labels=len(results),
        failed_runs=sum(result.failed_runs for result in results),
        abandoned_runs=sum(result.abandoned_runs for result in results),
        invalid_line_incidents=sum(result.invalid_line_incidents for result in results),
        pass_rate=mean(result.accepted_rate for result in results),
        recall=_mean_or_none([result.flagged_rate for result in violations]),
        false_positive_rate=_mean_or_none([result.rejected_rate for result in clean]),
        exact_priority_rate=_mean_or_none([result.exact_rate for result in with_priority]),
        accepted_priority_rate=_mean_or_none([result.accepted_rate for result in with_priority]),
    )
