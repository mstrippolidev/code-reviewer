"""
    ORM model for one finding of a review, so it has an id that feedback can point at.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base

CONTENT_CONSTRAINT = "uq_review_incidents_content"


class ReviewIncident(Base):
    """One incident an agent reported on one file; its `id` is the incident_id clients see."""

    __tablename__ = "review_incidents"
    __table_args__ = (
        UniqueConstraint("review_job_id", "file_path", "code_key", "content_digest", name=CONTENT_CONSTRAINT),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_job_id: Mapped[int] = mapped_column(ForeignKey("api.review_jobs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str]
    code_key: Mapped[str]
    priority: Mapped[str]
    line_position: Mapped[str]
    description: Mapped[str] = mapped_column(Text)
    advice: Mapped[str] = mapped_column(Text)
    content_digest: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
