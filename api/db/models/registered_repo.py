"""
    ORM model for a repo registered for review.
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, ForeignKey, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class RepoIndexStatus(str, Enum):
    """Lifecycle of a registered repo's content in the RAG index."""

    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"


class RegisteredRepo(Base):
    """A GitHub repo registered for review; unique per repo_id, since indexed content is scoped globally by it."""

    __tablename__ = "registered_repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    full_name: Mapped[str]
    default_branch: Mapped[str]
    registered_by_user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id"))
    status: Mapped[RepoIndexStatus] = mapped_column(
        SqlEnum(RepoIndexStatus, name="repo_index_status", inherit_schema=True),
        default=RepoIndexStatus.PENDING,
        server_default=RepoIndexStatus.PENDING.value,
    )
    status_reason: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
