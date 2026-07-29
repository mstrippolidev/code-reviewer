from enum import Enum

from pydantic import BaseModel, Field


class CodeKey(str, Enum):
    SOLID1 = "SOLID1"
    SOLID2 = "SOLID2"
    COH = "COH"
    COUP = "COUP"
    TEST = "TEST"
    TCASE = "TCASE"
    CONC = "CONC"
    CMPLX = "CMPLX"
    ARCH = "ARCH"
    BOUND = "BOUND"
    VAR = "VAR"
    DRY = "DRY"
    ERR = "ERR"
    CMT = "CMT"


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SizeStatus(str, Enum):
    NORMAL = "normal"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT_EXCEEDED = "hard_limit_exceeded"


class PrRecommendation(str, Enum):
    APPROVED = "APPROVED"
    NEEDS_WORK = "NEEDS_WORK"
    REJECTED = "REJECTED"


class Incident(BaseModel):
    priority: Priority = Field(
        description="Severity of this incident: critical, high, medium, or low."
    )
    line_position: str = Field(
        description=(
            "Location in the file as a 'start-end' string, e.g. '23-60' for a "
            "range or '32-32' for a single line. Never a bare integer."
        )
    )
    description: str = Field(
        description=(
            "One sentence naming the specific problem, referencing the actual "
            "function/class/variable involved rather than restating the rule."
        )
    )
    advice: str = Field(
        description="A concrete, actionable fix — what to rename, split, or extract."
    )
    code_key: CodeKey | None = Field(
        default=None,
        description=(
            "Which agent raised this incident. Omitted on a single agent's own "
            "output; set by the aggregator when merging multiple agents' results."
        ),
    )


class AgentReviewEntry(BaseModel):
    file_path: str | None = Field(
        default=None,
        description=(
            "Path to the reviewed file, relative to the repo root. None when "
            "reviewing a standalone snippet with no associated file — only "
            "meaningful for PR or whole-file reviews."
        ),
    )
    rating: int = Field(
        ge=0,
        le=100,
        description="Score for this agent's dimension only, starting at 100 and discounted per incident.",
    )
    code_key: CodeKey = Field(
        description="Identity of the agent producing this review. Must match the agent's own key."
    )
    incidents: list[Incident] = Field(
        description="All incidents this agent found in the file or chunk; empty if none."
    )


class AgentOutput(BaseModel):
    review: list[AgentReviewEntry] = Field(
        description="One entry per file or chunk this agent call covered."
    )


class AggregatedReviewEntry(BaseModel):
    file_path: str = Field(description="Path to the reviewed file, relative to the repo root.")
    rating: int = Field(
        ge=0,
        le=100,
        description="This file's rating after merging and weighting all agents that reviewed it.",
    )
    code_key: list[CodeKey] = Field(
        description="All agents that reported an incident on this file."
    )
    file_lines: str = Field(
        description="This file's total line count as a 'start-end' string, e.g. '1-320'."
    )
    size_status: SizeStatus = Field(
        description="Which file-size bucket this file falls into: normal, soft_limit, or hard_limit_exceeded."
    )
    agents_skipped: list[CodeKey] = Field(
        description="File agents that returned rating 0 for this file because it exceeded the hard limit."
    )
    skip_reason: str | None = Field(
        description="Why agents were skipped for this file, or null if none were."
    )
    incidents: list[Incident] = Field(
        description="All incidents found for this file across every agent that reviewed it."
    )


class SkippedFile(BaseModel):
    file_path: str = Field(description="Path to a file present in the PR but never reviewed.")
    reason: str = Field(
        description="Why this file was skipped, e.g. 'exceeded_pr_file_cap'."
    )


class Meta(BaseModel):
    total_files_in_pr: int = Field(
        description="Total files present in the PR submission, before any PR-level file cap was applied."
    )
    total_files_reviewed: int = Field(description="Count of files included in this review.")
    overall_rating: float = Field(
        ge=0,
        le=100,
        description="Weighted average rating across all agents and files, using AGENT_WEIGHTS.",
    )
    critical_incidents: int = Field(description="Total critical-priority incidents across all files.")
    high_incidents: int = Field(description="Total high-priority incidents across all files.")
    medium_incidents: int = Field(description="Total medium-priority incidents across all files.")
    low_incidents: int = Field(description="Total low-priority incidents across all files.")
    agents_run: list[CodeKey] = Field(description="Full roster of agents invoked for this review.")
    pr_recommendation: PrRecommendation = Field(
        description="APPROVED, NEEDS_WORK, or REJECTED based on the rating and incident thresholds."
    )
    rejection_reason: str | None = Field(
        description="Human-readable reason for REJECTED, or null otherwise."
    )
    skipped_files: list[SkippedFile] = Field(
        description="Files present in the PR but never reviewed; empty if none were skipped."
    )


class AggregatorOutput(BaseModel):
    meta: Meta = Field(description="Summary statistics and the final PR recommendation.")
    review: list[AggregatedReviewEntry] = Field(
        description="Per-file merged review results."
    )
