"""
    ORM model for the raw source of one file a review job reviewed, when that source is not in the index.
"""
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ReviewJobFile(Base):
    """A file's content kept with its review job: a guest's or user's submitted file, or a pull request's file.

    It is the source of truth for that review, like IndexedFile is for a repo's indexed files, and it is never
    written to the vector store.
    """

    __tablename__ = "review_job_files"
    __table_args__ = (UniqueConstraint("review_job_id", "file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    review_job_id: Mapped[int] = mapped_column(ForeignKey("api.review_jobs.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
