"""
    ORM model for the panel's decision on one file as a repo's exemplar for one agent.
"""
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint, func
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class PromotionOutcome(str, Enum):
    """What the judge panel decided; `needs_review` is a split vote waiting for a human."""

    PROMOTED = "promoted"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class ExemplarPromotion(Base):
    """One decision per file content, so a rejected or split file is never judged twice."""

    __tablename__ = "exemplar_promotions"
    __table_args__ = (
        UniqueConstraint("repo_id", "file_path", "code_key", "content_digest", name="uq_exemplar_promotions_content"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str]
    code_key: Mapped[str]
    content_digest: Mapped[str]
    outcome: Mapped[PromotionOutcome] = mapped_column(
        SqlEnum(
            PromotionOutcome,
            name="promotion_outcome",
            inherit_schema=True,
            values_callable=lambda members: [member.value for member in members],
        )
    )
    decided_at: Mapped[datetime] = mapped_column(server_default=func.now())
