"""
    Schemas for intake screen (guardrails)
"""
from pydantic import BaseModel, Field


class ScreeningVerdict(BaseModel):
    """Pass/fail result of a single intake screen (code detection or prompt-injection),
    shared by both since they are structurally identical checks."""

    is_valid: bool = Field(description="Whether the content passes this screen.")
    reason: str = Field(description="One sentence justifying the verdict.")
