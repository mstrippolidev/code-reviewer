"""
    Kafka message for the exemplar-promotion.requested topic: ids only, the file's code is read from the index.
"""
import uuid

from pydantic import BaseModel

from code_reviewer.schemas.review import CodeKey


class ExemplarPromotionRequestedMessage(BaseModel):
    """One file a review rated 100 for one agent, queued for the judge panel."""

    review_id: uuid.UUID
    repo_id: int
    file_path: str
    code_key: CodeKey
