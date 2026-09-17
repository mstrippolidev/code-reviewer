"""
    ORM model for one file's indexing status within a registered repo.
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class IndexedFileStatus(str, Enum):
    """Lifecycle of one file as the indexing worker walks and processes it."""

    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    SKIPPED = "skipped"
    FAILED = "failed"


class IndexedFile(Base):
    """Per-file indexing status for one registered repo; one row per (repo_id, file_path)."""

    __tablename__ = "indexed_files"
    __table_args__ = (UniqueConstraint("repo_id", "file_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("api.registered_repos.repo_id"), index=True)
    file_path: Mapped[str] = mapped_column(String)
    status: Mapped[IndexedFileStatus] = mapped_column(
        SqlEnum(IndexedFileStatus, name="indexed_file_status", inherit_schema=True),
        default=IndexedFileStatus.PENDING,
        server_default=IndexedFileStatus.PENDING.value,
    )
    status_reason: Mapped[str | None]
    indexed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
