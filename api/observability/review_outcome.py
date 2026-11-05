"""
    Derives what a finished review looks like from its report, without touching any instrument.
"""
from enum import StrEnum

from pydantic import BaseModel

from api.schemas.reviews import ReviewRequestedMessage
from code_reviewer.pipeline.orchestrator import AGENT_EXECUTION_FAILED_REASON, GUARD_EXECUTION_FAILED_REASON
from code_reviewer.schemas.review import AggregatorOutput

UNEXPECTED_SKIP_REASONS = frozenset({AGENT_EXECUTION_FAILED_REASON, GUARD_EXECUTION_FAILED_REASON})


class ReviewKind(StrEnum):
    REPO = "repo"
    PULL_REQUEST = "pull_request"
    GUEST = "guest"
    REPOLESS = "repoless"


class ReviewOutcome(BaseModel):
    file_count: int
    failed_file_count: int
    size_status_counts: dict[str, int]


def review_kind_of(message: ReviewRequestedMessage) -> ReviewKind:
    """Which of the four review shapes this message is."""
    if message.is_pull_request_review:
        return ReviewKind.PULL_REQUEST
    if message.is_guest_review:
        return ReviewKind.GUEST
    if message.has_uploaded_files:
        return ReviewKind.REPOLESS
    return ReviewKind.REPO


def summarize_review(result: AggregatorOutput) -> ReviewOutcome:
    """Counts a report's reviewed files, files lost to an unexpected failure, and files per size status."""
    size_status_counts: dict[str, int] = {}
    for file_entry in result.review:
        size_status = file_entry.size_status.value
        size_status_counts[size_status] = size_status_counts.get(size_status, 0) + 1
    failed_files = [skipped for skipped in result.meta.skipped_files if skipped.reason in UNEXPECTED_SKIP_REASONS]
    return ReviewOutcome(
        file_count=len(result.review),
        failed_file_count=len(failed_files),
        size_status_counts=size_status_counts,
    )
