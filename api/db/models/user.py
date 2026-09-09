"""
    ORM model for a user authenticated via GitHub OAuth.
"""
from datetime import datetime

from sqlalchemy import BigInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class User(Base):
    """A person authenticated via GitHub OAuth."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    github_username: Mapped[str]
    email: Mapped[str | None]
    avatar_url: Mapped[str | None]
    encrypted_github_token: Mapped[str]
    github_granted_scopes: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())