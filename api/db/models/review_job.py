"""
    ORM model for one ad-hoc review submission — a registered repo's indexed files, or a guest's raw files.
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, BigInteger, ForeignKey
from sqlalchemy import Enum as SqlEnum
from sqlalchemy import Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class ReviewJobStatus(str, Enum):
    """Lifecycle of one review submission, from request to a finished report."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewJob(Base):
    """A user-submitted set of already-indexed files, reviewed together as one job."""

    __tablename__ = "review_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, index=True, default=uuid.uuid4)
    repo_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"), index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("api.users.id"))
    guest_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("api.guest_sessions.id", ondelete="CASCADE"), index=True
    )
    file_paths: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[ReviewJobStatus] = mapped_column(
        SqlEnum(
            ReviewJobStatus,
            name="review_job_status",
            inherit_schema=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ReviewJobStatus.PENDING,
        server_default=ReviewJobStatus.PENDING.value,
    )
    status_reason: Mapped[str | None]
    result: Mapped[dict | None] = mapped_column(JSON)
    agent_entries: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    completed_at: Mapped[datetime | None]
