"""
    Output schema for the DRY duplication judge — one LLM call batches
    every surviving candidate for a single chunk under review, and returns
    one verdict per candidate rather than a bare yes/no, since a confirmed
    duplicate becomes the reported incident directly.
"""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from code_reviewer.schemas.review import Priority


class DryJudgeVerdict(BaseModel):
    candidate_index: int = Field(
        description=(
            "Which numbered candidate in the prompt this verdict judges, "
            "in the same order the candidates were given. Every candidate "
            "gets exactly one verdict."
        )
    )
    is_duplicate: bool = Field(
        description=(
            "True if this candidate genuinely duplicates the chunk under "
            "review, in whole or in part. False if it only looks similar."
        )
    )
    priority: Priority | None = Field(
        default=None,
        description="Severity of the duplication. Set only when is_duplicate is True.",
    )
    line_position: str | None = Field(
        default=None,
        description=(
            "The duplicated range in the chunk under review, as a "
            "'start-end' string, e.g. '23-30'. Never a bare integer, and "
            "never a location in the candidate. Set only when is_duplicate "
            "is True."
        ),
    )
    description: str | None = Field(
        default=None,
        description=(
            "One sentence naming what is duplicated and where the "
            "candidate's copy lives. Set only when is_duplicate is True."
        ),
    )
    advice: str | None = Field(
        default=None,
        description=(
            "A concrete next step: extract a named shared function/method "
            "and where it should live, or, if consolidating would force "
            "unrelated concerns together, say to leave the duplication as "
            "is and why. Set only when is_duplicate is True."
        ),
    )

    @model_validator(mode="after")
    def _confirmed_duplicate_carries_a_full_finding(self) -> Self:
        """Failing this raises during structured-output parsing, which
        retry_model already catches and corrects — a cheaper fix than
        letting a half-filled verdict reach Incident construction later
        and blow up with no chance to self-correct."""
        if self.is_duplicate and None in (self.priority, self.line_position, self.description, self.advice):
            raise ValueError(
                "is_duplicate=True requires priority, line_position, description, and advice to all be set."
            )
        return self


class DryJudgeOutput(BaseModel):
    verdicts: list[DryJudgeVerdict] = Field(
        min_length=1,
        description=(
            "One verdict per candidate given in this call, covering every "
            "candidate exactly once, in the order they were given."
        ),
    )
