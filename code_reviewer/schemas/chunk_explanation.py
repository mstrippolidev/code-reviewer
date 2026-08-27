"""
    Schema for a code chunk's short, embedding-oriented explanation.
"""
from pydantic import BaseModel, Field


class ChunkExplanation(BaseModel):
    explanation: str = Field(
        description=(
            "One or two concise sentences describing what this code chunk does, meant to "
            "be embedded alongside the code for semantic duplicate search — not a "
            "docstring, not a narration of its implementation."
        )
    )
