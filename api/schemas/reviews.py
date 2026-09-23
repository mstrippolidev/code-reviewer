import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.db.models.review_job import ReviewJobStatus
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import AgentReviewEntry, AggregatorOutput, CodeKey


class ReviewSubmissionRequest(BaseModel):
    """Files the client wants reviewed together, all already indexed for this repo."""

    file_paths: list[str] = Field(min_length=1, max_length=get_settings().max_files_per_submission)


class ReviewJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: uuid.UUID
    repo_id: int
    status: ReviewJobStatus
    status_reason: str | None
    file_paths: list[str]
    result: AggregatorOutput | None
    agent_entries: dict[str, dict[str, AgentReviewEntry]] | None


class ReviewFileProgressMessage(BaseModel):
    """Published once a single file settles (reviewed or given up on); relayed live over the SSE stream."""

    review_id: uuid.UUID
    file_path: str
    failed: bool = False


class ReviewAgentProgressMessage(BaseModel):
    """Published the instant one agent finishes reviewing one file; relayed live over the SSE stream."""

    review_id: uuid.UUID
    file_path: str
    code_key: CodeKey
    entry: AgentReviewEntry


class ReviewStatusMessage(BaseModel):
    """Published on every review-job status change; the SSE route relays it live and stops on a terminal state."""

    review_id: uuid.UUID
    repo_id: int
    status: ReviewJobStatus
    status_reason: str | None
    file_paths: list[str]
    result: AggregatorOutput | None = None
    agent_entries: dict[str, dict[str, AgentReviewEntry]] | None = None


class ReviewRequestedMessage(BaseModel):
    """Kafka message payload published to the review.requested topic."""

    review_id: uuid.UUID
    repo_id: int
    owner_id: int
    requested_by_user_id: int
    file_paths: list[str]
