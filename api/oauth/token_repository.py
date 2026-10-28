import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.oauth_token import OAuthToken


class OAuthTokenRepository:
    """Database access for OAuth tokens; the caller decides when to commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, token: OAuthToken) -> None:
        self._session.add(token)

    async def find_by_access_hash(self, access_token_hash: str) -> OAuthToken | None:
        statement = select(OAuthToken).where(OAuthToken.access_token_hash == access_token_hash)
        return await self._session.scalar(statement)

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> OAuthToken | None:
        statement = select(OAuthToken).where(OAuthToken.refresh_token_hash == refresh_token_hash)
        return await self._session.scalar(statement)

    async def mark_refresh_used(self, token_id: int, used_at: datetime) -> bool:
        """Returns False when another request already used this refresh token."""
        statement = (
            update(OAuthToken)
            .where(OAuthToken.id == token_id, OAuthToken.refresh_used_at.is_(None))
            .values(refresh_used_at=used_at)
        )
        result = await self._session.execute(statement)
        return result.rowcount == 1

    async def revoke_family(self, family_id: uuid.UUID, revoked_at: datetime) -> None:
        statement = (
            update(OAuthToken)
            .where(OAuthToken.family_id == family_id, OAuthToken.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        await self._session.execute(statement)

    async def commit(self) -> None:
        await self._session.commit()
