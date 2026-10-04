import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.db.models.review_job import ReviewJobStatus
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import AgentReviewEntry, AggregatorOutput, CodeKey


MAX_GUEST_FILES = 5


class ReviewSubmissionRequest(BaseModel):
    """Files the client wants reviewed together, all already indexed for this repo."""

    file_paths: list[str] = Field(min_length=1, max_length=get_settings().max_files_per_submission)


class GuestSubmittedFile(BaseModel):
    file_path: str
    content: str


class GuestReviewSubmissionRequest(BaseModel):
    """Raw files a guest wants reviewed together — there is no indexed repo to look them up from."""

    files: list[GuestSubmittedFile] = Field(min_length=1, max_length=MAX_GUEST_FILES)

    @model_validator(mode="after")
    def _has_unique_file_paths(self) -> "GuestReviewSubmissionRequest":
        file_paths = [file.file_path for file in self.files]
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("Each submitted file must have a distinct file_path")
        return self


class ReviewFileContentRead(BaseModel):
    """The stored source of one file a guest submitted, for a client rendering it alongside a review."""

    model_config = ConfigDict(from_attributes=True)

    file_path: str
    content: str


class ReviewJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    review_id: uuid.UUID
    repo_id: int | None
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
    repo_id: int | None
    status: ReviewJobStatus
    status_reason: str | None
    file_paths: list[str]
    result: AggregatorOutput | None = None
    agent_entries: dict[str, dict[str, AgentReviewEntry]] | None = None


class ReviewFileProgressEnvelope(BaseModel):
    """review.progress wire shape for a file event; `kind` lets one topic carry all three event types in order."""

    kind: Literal["file"] = "file"
    event: ReviewFileProgressMessage


class ReviewAgentProgressEnvelope(BaseModel):
    """review.progress wire shape for an agent event."""

    kind: Literal["agent"] = "agent"
    event: ReviewAgentProgressMessage


class ReviewStatusEnvelope(BaseModel):
    """review.progress wire shape for a job status event."""

    kind: Literal["status"] = "status"
    event: ReviewStatusMessage


ReviewProgressEnvelope = Annotated[
    ReviewFileProgressEnvelope | ReviewAgentProgressEnvelope | ReviewStatusEnvelope, Field(discriminator="kind")
]


class ReviewRequestedMessage(BaseModel):
    """Kafka message payload published to the review.requested topic.

    Exactly one shape per message: a repo review (repo_id, owner_id,
    requested_by_user_id) whose content is loaded from IndexedFile rows, or a
    guest review (guest_session_id) whose content is loaded from GuestReviewFile rows.
    """

    review_id: uuid.UUID
    file_paths: list[str]
    repo_id: int | None = None
    owner_id: int | None = None
    requested_by_user_id: int | None = None
    guest_session_id: int | None = None

    @model_validator(mode="after")
    def _is_exactly_one_shape(self) -> "ReviewRequestedMessage":
        is_repo_review = None not in (self.repo_id, self.owner_id, self.requested_by_user_id)
        is_guest_review = self.guest_session_id is not None
        if is_repo_review == is_guest_review:
            raise ValueError("A review.requested message must be exactly one of a repo review or a guest review")
        return self

    @property
    def is_guest_review(self) -> bool:
        return self.guest_session_id is not None
