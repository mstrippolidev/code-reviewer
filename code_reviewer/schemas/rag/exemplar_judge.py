"""
    Output schema for the exemplar judges: each one says, per retrieved candidate,
    whether it is a good reference for the code being reviewed.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ExemplarRelevance(str, Enum):
    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"


class ExemplarVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(
        description=(
            "Which numbered candidate in the prompt this verdict judges, in "
            "the same order the candidates were given. Every candidate gets "
            "exactly one verdict."
        )
    )
    status: ExemplarRelevance = Field(
        description=(
            "relevant if this candidate shows how to handle the same kind of design "
            "problem the code under review has, so a reviewer could point at it as a "
            "reference for what good looks like here; not_relevant otherwise."
        )
    )


class ExemplarJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[ExemplarVerdict] = Field(
        min_length=1,
        description="One verdict per candidate given in this call, covering every candidate exactly once, in order.",
    )
