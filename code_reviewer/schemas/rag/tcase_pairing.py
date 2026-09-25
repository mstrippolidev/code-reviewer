"""
    Output schemas for TCASE's corrective test-file pairing: the judge
    confirming which retrieved candidates really test a source file, and
    the rewrite producing a new search query when none did.
"""
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PairingMatchStatus(str, Enum):
    MATCH = "match"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


class PairingVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(
        description=(
            "Which numbered candidate in the prompt this verdict judges, in "
            "the same order the candidates were given. Every candidate gets "
            "exactly one verdict."
        )
    )
    status: PairingMatchStatus = Field(
        description=(
            "match if this candidate is genuinely a test file for the source "
            "file, no_match if it clearly is not, ambiguous if the content "
            "leaves it genuinely unclear."
        )
    )
    reasoning: str = Field(
        description="One sentence naming the evidence for this status, e.g. which source symbols it imports and asserts on."
    )


class PairingJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[PairingVerdict] = Field(
        min_length=1,
        description="One verdict per candidate given in this call, covering every candidate exactly once, in order.",
    )


class PairingQueryRewriteOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description=(
            "Two or three sentences describing the test file being searched "
            "for — what it imports, exercises, and asserts — written the way "
            "that test file's own behavior would be summarized."
        )
    )
