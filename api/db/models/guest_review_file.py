"""
    ORM model for the raw source of one file a guest submitted for review.
"""
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class GuestReviewFile(Base):
    """A guest-submitted file's content — the source of truth for its review, like IndexedFile is for a repo's."""

    __tablename__ = "guest_review_files"
    __table_args__ = (UniqueConstraint("review_job_id", "file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    review_job_id: Mapped[int] = mapped_column(ForeignKey("api.review_jobs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
