"""
    ORM model for one rater's thumbs up or down on one incident.
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class FeedbackVerdict(str, Enum):
    """Whether the rater found the incident right."""

    UP = "up"
    DOWN = "down"


class FeedbackReason(str, Enum):
    """Why a thumbs-down incident was wrong; `other` is explained in the note."""

    NOT_TRUE = "not_true"
    WRONG_LINES = "wrong_lines"
    NOT_ACTIONABLE = "not_actionable"
    WRONG_SEVERITY = "wrong_severity"
    OTHER = "other"


def _enum_of(enum_class: type[Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_class,
        name=name,
        inherit_schema=True,
        values_callable=lambda members: [member.value for member in members],
    )


class FindingFeedback(Base):
    """A user's or guest's rating of one incident; rating again replaces it."""

    __tablename__ = "finding_feedback"
    __table_args__ = (UniqueConstraint("incident_id", "rater_key", name="uq_finding_feedback_incident_rater"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("api.review_incidents.id", ondelete="CASCADE"))
    rater_key: Mapped[str]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("api.users.id", ondelete="CASCADE"), index=True)
    guest_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("api.guest_sessions.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[FeedbackVerdict] = mapped_column(_enum_of(FeedbackVerdict, "feedback_verdict"))
    reason: Mapped[FeedbackReason | None] = mapped_column(_enum_of(FeedbackReason, "feedback_reason"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
