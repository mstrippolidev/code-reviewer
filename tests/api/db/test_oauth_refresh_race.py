"""
    Test for two simultaneous refreshes of one refresh token against the real local Postgres.

    Unlike the other db tests this one cannot run inside a rolled-back transaction: the two requests need
    separate connections that see each other's commits. It commits real rows under unique ids and deletes
    them at the end. Requires the migrations to have been applied (`alembic upgrade head`).
"""
import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.config.settings import get_api_settings
from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_token import OAuthToken
from api.db.models.user import User
from api.oauth.errors import InvalidGrantError
from api.oauth.token_repository import OAuthTokenRepository
from api.oauth.token_service import IssuedTokens, OAuthTokenService, TokenLifetimes

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

USER_GITHUB_ID = 940_000_001
CLIENT_ID = "race-test-client"
LIFETIMES = TokenLifetimes(access_seconds=3600, refresh_idle_seconds=7 * 86400, refresh_absolute_seconds=30 * 86400)


class BarrierRepository(OAuthTokenRepository):
    """Holds every caller after it has read the token, so all of them race on the same unused row."""

    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> OAuthToken | None:
        row = await super().find_by_refresh_hash(refresh_token_hash)
        await self._barrier.wait()
        return row


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(get_api_settings().async_database_url)
    yield test_engine
    async with async_sessionmaker(test_engine)() as cleanup_session:
        await cleanup_session.execute(delete(User).where(User.github_id == USER_GITHUB_ID))
        await cleanup_session.execute(delete(OAuthClient).where(OAuthClient.client_id == CLIENT_ID))
        await cleanup_session.commit()
    await test_engine.dispose()


async def _issue_committed_tokens(engine: AsyncEngine) -> IssuedTokens:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user = User(
            github_id=USER_GITHUB_ID,
            github_username="oauth-race-test",
            encrypted_github_token="unused",
            github_granted_scopes="repo",
        )
        session.add(user)
        session.add(OAuthClient(client_id=CLIENT_ID, client_name="Race test", redirect_uris=["http://localhost:1/cb"]))
        await session.flush()
        return await OAuthTokenService(OAuthTokenRepository(session), LIFETIMES).issue(user.id, CLIENT_ID)


async def _refresh_in_own_session(engine: AsyncEngine, barrier: asyncio.Barrier, refresh_token: str) -> IssuedTokens:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        service = OAuthTokenService(BarrierRepository(session, barrier), LIFETIMES)
        return await service.refresh(refresh_token, CLIENT_ID)


async def test_two_simultaneous_refreshes_of_one_token_leave_one_winner_and_a_revoked_family(
    engine: AsyncEngine,
) -> None:
    tokens = await _issue_committed_tokens(engine)
    barrier = asyncio.Barrier(2)

    results = await asyncio.gather(
        *(_refresh_in_own_session(engine, barrier, tokens.refresh_token) for _ in range(2)),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, IssuedTokens)]
    losers = [result for result in results if isinstance(result, InvalidGrantError)]
    assert (len(winners), len(losers)) == (1, 1)
    assert "concurrently" in str(losers[0])
    async with async_sessionmaker(engine)() as session:
        rows = (await session.scalars(select(OAuthToken).where(OAuthToken.client_id == CLIENT_ID))).all()
        assert len(rows) == 2
        assert all(row.revoked_at is not None for row in rows)
