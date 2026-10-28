import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from api.db.models.oauth_token import OAuthToken
from api.oauth.errors import InvalidGrantError
from api.oauth.token_repository import OAuthTokenRepository
from api.oauth.token_secrets import generate_secret, hash_secret

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Naive UTC, matching the naive datetime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


class TokenLifetimes(BaseModel):
    access_seconds: int
    refresh_idle_seconds: int
    refresh_absolute_seconds: int


class IssuedTokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class OAuthTokenService:
    """Issues access and refresh tokens, rotates refresh tokens and revokes whole token families."""

    def __init__(
        self,
        repository: OAuthTokenRepository,
        lifetimes: TokenLifetimes,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._lifetimes = lifetimes
        self._clock = clock

    async def issue(self, user_id: int, client_id: str) -> IssuedTokens:
        now = self._clock()
        tokens = self._add_token_row(
            user_id=user_id, client_id=client_id, family_id=uuid.uuid4(), authorized_at=now, now=now
        )
        await self._repository.commit()
        return tokens

    async def refresh(self, refresh_token: str, client_id: str) -> IssuedTokens:
        now = self._clock()
        row = await self._repository.find_by_refresh_hash(hash_secret(refresh_token))
        if row is None:
            raise self._reject("unknown refresh token")
        self._require_same_client(row, client_id)
        if row.revoked_at is not None:
            raise self._reject("refresh token is revoked", row)
        if row.refresh_used_at is not None:
            await self._revoke_family(row, now)
            raise self._reject("refresh token reused, token family revoked", row)
        self._require_not_expired(row, now)
        if not await self._repository.mark_refresh_used(row.id, now):
            await self._revoke_family(row, now)
            raise self._reject("refresh token reused concurrently, token family revoked", row)
        tokens = self._add_token_row(
            user_id=row.user_id,
            client_id=row.client_id,
            family_id=row.family_id,
            authorized_at=row.authorized_at,
            now=now,
        )
        await self._repository.commit()
        return tokens

    async def revoke(self, token: str) -> None:
        """Revokes the token's whole family; an unknown token is ignored."""
        token_hash = hash_secret(token)
        row = await self._repository.find_by_refresh_hash(token_hash)
        if row is None:
            row = await self._repository.find_by_access_hash(token_hash)
        if row is None:
            return
        await self._revoke_family(row, self._clock())

    def _add_token_row(
        self, *, user_id: int, client_id: str, family_id: uuid.UUID, authorized_at: datetime, now: datetime
    ) -> IssuedTokens:
        access_token, refresh_token = generate_secret(), generate_secret()
        absolute_deadline = authorized_at + timedelta(seconds=self._lifetimes.refresh_absolute_seconds)
        idle_deadline = now + timedelta(seconds=self._lifetimes.refresh_idle_seconds)
        self._repository.add(
            OAuthToken(
                access_token_hash=hash_secret(access_token),
                access_expires_at=now + timedelta(seconds=self._lifetimes.access_seconds),
                refresh_token_hash=hash_secret(refresh_token),
                refresh_expires_at=min(idle_deadline, absolute_deadline),
                family_id=family_id,
                authorized_at=authorized_at,
                user_id=user_id,
                client_id=client_id,
            )
        )
        return IssuedTokens(
            access_token=access_token, refresh_token=refresh_token, expires_in=self._lifetimes.access_seconds
        )

    def _require_same_client(self, row: OAuthToken, client_id: str) -> None:
        if row.client_id != client_id:
            raise self._reject("refresh token belongs to another client", row)

    def _require_not_expired(self, row: OAuthToken, now: datetime) -> None:
        if now >= row.refresh_expires_at:
            raise self._reject("refresh token expired", row)
        absolute_deadline = row.authorized_at + timedelta(seconds=self._lifetimes.refresh_absolute_seconds)
        if now >= absolute_deadline:
            raise self._reject("authorization reached its absolute lifetime", row)

    async def _revoke_family(self, row: OAuthToken, now: datetime) -> None:
        await self._repository.revoke_family(row.family_id, now)
        await self._repository.commit()

    def _reject(self, reason: str, row: OAuthToken | None = None) -> InvalidGrantError:
        user_id = row.user_id if row is not None else None
        client_id = row.client_id if row is not None else None
        logger.warning("OAuth refresh rejected: %s (user_id=%s, client_id=%s)", reason, user_id, client_id)
        return InvalidGrantError(reason)
