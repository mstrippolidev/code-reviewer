"""
    ORM model for an app (Claude Code, Cursor, ...) that registered itself to request OAuth tokens.
"""
from datetime import datetime

from sqlalchemy import JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class OAuthClient(Base):
    """A public OAuth client: it holds no secret, so PKCE is what protects its authorization codes."""

    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
