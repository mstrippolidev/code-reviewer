"""
    ORM model for one request to find out whether a snippet already exists in a registered repo.
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, BigInteger, ForeignKey, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class SimilarCodeSearchStatus(str, Enum):
    """Where a search stands; `completed`, `rejected` and `failed` are final."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class SimilarCodeSearch(Base):
    """A snippet checked against one repo's indexed history, readable only by the user who asked."""

    __tablename__ = "similar_code_searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, index=True, default=uuid.uuid4)
    repo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"), index=True
    )
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id"))
    code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SimilarCodeSearchStatus] = mapped_column(
        SqlEnum(
            SimilarCodeSearchStatus,
            name="similar_code_search_status",
            inherit_schema=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=SimilarCodeSearchStatus.PENDING,
        server_default=SimilarCodeSearchStatus.PENDING.value,
    )
    status_reason: Mapped[str | None]
    incidents: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None]
