from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.db.models.finding_feedback import FeedbackReason, FeedbackVerdict

MAX_NOTE_LENGTH = 500


class FeedbackWrite(BaseModel):
    """A rating of one incident: a thumbs up, or a thumbs down with the reason it was wrong."""

    incident_id: int
    verdict: FeedbackVerdict
    reason: FeedbackReason | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)

    @model_validator(mode="after")
    def _reason_belongs_to_a_thumbs_down(self) -> Self:
        if self.reason is not None and self.verdict is not FeedbackVerdict.DOWN:
            raise ValueError("A reason can only be given with a thumbs down")
        return self


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    incident_id: int
    verdict: FeedbackVerdict
    reason: FeedbackReason | None
    note: str | None
