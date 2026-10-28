"""
    ORM model for an issued access and refresh token pair.
"""
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class OAuthToken(Base):
    """One link in a refresh-token chain; every rotation of one authorization shares a family_id."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    access_expires_at: Mapped[datetime]
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    refresh_expires_at: Mapped[datetime]
    refresh_used_at: Mapped[datetime | None]
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    authorized_at: Mapped[datetime]
    user_id: Mapped[int] = mapped_column(ForeignKey("api.users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("api.oauth_clients.client_id", ondelete="CASCADE")
    )
    revoked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
