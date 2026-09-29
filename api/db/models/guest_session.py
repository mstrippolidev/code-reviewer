"""
    ORM model for a lightweight, repo-less guest identity — no GitHub account behind it.
"""
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class GuestSession(Base):
    """A browser session reviewing ad hoc files without a GitHub login or registered repo."""

    __tablename__ = "guest_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
