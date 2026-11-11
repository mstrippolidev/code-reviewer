"""
    Reads a saved evaluation report, including ones written before newer fields existed.
"""
from pathlib import Path
from typing import Any

from pydantic import BaseModel, model_validator

from evaluation.run_record import RunRecord
from evaluation.scoring import LabelResult


class ReportFile(BaseModel):
    model_by_agent: dict[str, str]
    runs_per_label: int
    run_record: RunRecord | None = None
    results: dict[str, list[LabelResult]]

    @model_validator(mode="before")
    @classmethod
    def name_the_model_of_an_early_report(cls, data: Any) -> Any:
        """The first reports held one `model` for every agent instead of `model_by_agent`."""
        if isinstance(data, dict) and "model_by_agent" not in data and "model" in data:
            return {**data, "model_by_agent": {agent: data["model"] for agent in data.get("results", {})}}
        return data


def read_report(path: Path) -> ReportFile:
    """The parts of a saved report that comparison and baselines need; scores are recomputed, not read."""
    return ReportFile.model_validate_json(path.read_text())
