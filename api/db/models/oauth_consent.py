"""
    ORM model recording that a user already approved an OAuth client.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class OAuthConsent(Base):
    """A user's approval of a client; while it exists, that client skips the consent screen."""

    __tablename__ = "oauth_consents"
    __table_args__ = (UniqueConstraint("user_id", "client_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id", ondelete="CASCADE"))
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("api.oauth_clients.client_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
