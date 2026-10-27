"""
    ORM model linking a user to a registered repo in their list.
"""
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class UserRepo(Base):
    """One user's link to a registered repo; many users can be linked to the same repo."""

    __tablename__ = "user_repos"
    __table_args__ = (UniqueConstraint("user_id", "repo_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id", ondelete="CASCADE"))
    repo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("api.registered_repos.repo_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
