import uuid

from pydantic import BaseModel, ConfigDict, Field

from api.db.models.similar_code_search import SimilarCodeSearchStatus
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import Incident


class SimilarCodeRequest(BaseModel):
    """A snippet to check against a registered repo's indexed history."""

    code: str = Field(min_length=1, max_length=get_settings().max_submission_characters)


class SimilarCodeSearchRead(BaseModel):
    """A search's progress; `incidents` is set once it is `completed` and is empty when nothing in the repo resembles the snippet."""

    model_config = ConfigDict(from_attributes=True)

    search_id: uuid.UUID
    status: SimilarCodeSearchStatus
    status_reason: str | None
    incidents: list[Incident] | None


class SimilarCodeRequestedMessage(BaseModel):
    """Kafka message payload published to the similar-code.requested topic; the snippet itself stays in the database."""

    search_id: uuid.UUID
    repo_id: int
