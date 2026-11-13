"""
    ORM models for DRY calibration: code pairs a person labels as duplicate or not, and the labels themselves.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class CalibrationPair(Base):
    """Two code fragments shown side by side; loaded from a file, never created by a request."""

    __tablename__ = "calibration_pairs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[str] = mapped_column(unique=True, index=True)
    left_file_path: Mapped[str]
    left_chunk_name: Mapped[str]
    left_start_line: Mapped[int]
    left_end_line: Mapped[int]
    left_code: Mapped[str] = mapped_column(Text)
    right_file_path: Mapped[str]
    right_chunk_name: Mapped[str]
    right_start_line: Mapped[int]
    right_end_line: Mapped[int]
    right_code: Mapped[str] = mapped_column(Text)


class CalibrationLabel(Base):
    """One user's answer for one pair; answering again replaces it."""

    __tablename__ = "calibration_labels"
    __table_args__ = (UniqueConstraint("pair_id", "user_id", name="uq_calibration_labels_pair_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pair_id: Mapped[int] = mapped_column(ForeignKey("api.calibration_pairs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id", ondelete="CASCADE"), index=True)
    is_duplicate: Mapped[bool]
    note: Mapped[str | None] = mapped_column(Text)
    labeled_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
