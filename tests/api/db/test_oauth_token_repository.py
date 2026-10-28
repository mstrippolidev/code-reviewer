"""
    Tests for OAuthTokenRepository, and OAuthTokenService on top of it, against the real local Postgres.

    Every test runs inside a transaction that is rolled back at the end, so nothing is persisted.
    Requires the migrations to have been applied (`alembic upgrade head`).
"""
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.config.settings import get_api_settings
from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_token import OAuthToken
from api.db.models.user import User
from api.oauth.errors import InvalidGrantError
from api.oauth.token_repository import OAuthTokenRepository
from api.oauth.token_secrets import hash_secret
from api.oauth.token_service import OAuthTokenService, TokenLifetimes

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

USER_GITHUB_ID = 930_000_001
CLIENT_ID = "repo-test-client"
LIFETIMES = TokenLifetimes(access_seconds=3600, refresh_idle_seconds=7 * 86400, refresh_absolute_seconds=30 * 86400)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_api_settings().async_database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        test_session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)

        yield test_session

        await test_session.close()
        await transaction.rollback()
    await engine.dispose()


async def _add_user_and_client(session: AsyncSession) -> User:
    user = User(
        github_id=USER_GITHUB_ID,
        github_username="oauth-repo-test",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    session.add(OAuthClient(client_id=CLIENT_ID, client_name="Test", redirect_uris=["http://localhost:1/cb"]))
    await session.flush()
    return user


def _token(user: User, suffix: str, family_id: uuid.UUID) -> OAuthToken:
    now = datetime.utcnow()
    return OAuthToken(
        access_token_hash=f"access-{suffix}",
        access_expires_at=now + timedelta(hours=1),
        refresh_token_hash=f"refresh-{suffix}",
        refresh_expires_at=now + timedelta(days=7),
        family_id=family_id,
        authorized_at=now,
        user_id=user.id,
        client_id=CLIENT_ID,
    )


async def test_a_token_is_found_by_either_hash(session: AsyncSession) -> None:
    user = await _add_user_and_client(session)
    repository = OAuthTokenRepository(session)
    repository.add(_token(user, "a", uuid.uuid4()))
    await session.flush()

    by_access = await repository.find_by_access_hash("access-a")
    by_refresh = await repository.find_by_refresh_hash("refresh-a")

    assert by_access is not None and by_access is by_refresh


async def test_an_unknown_hash_finds_nothing(session: AsyncSession) -> None:
    repository = OAuthTokenRepository(session)

    assert await repository.find_by_access_hash("nope") is None
    assert await repository.find_by_refresh_hash("nope") is None


async def test_a_refresh_token_can_be_marked_used_only_once(session: AsyncSession) -> None:
    user = await _add_user_and_client(session)
    repository = OAuthTokenRepository(session)
    token = _token(user, "a", uuid.uuid4())
    repository.add(token)
    await session.flush()

    first = await repository.mark_refresh_used(token.id, datetime.utcnow())
    second = await repository.mark_refresh_used(token.id, datetime.utcnow())

    assert (first, second) == (True, False)


async def test_revoking_a_family_leaves_other_families_alone(session: AsyncSession) -> None:
    user = await _add_user_and_client(session)
    repository = OAuthTokenRepository(session)
    doomed_family = uuid.uuid4()
    repository.add(_token(user, "doomed-1", doomed_family))
    repository.add(_token(user, "doomed-2", doomed_family))
    repository.add(_token(user, "kept", uuid.uuid4()))
    await session.flush()

    await repository.revoke_family(doomed_family, datetime.utcnow())

    for suffix, revoked in [("doomed-1", True), ("doomed-2", True), ("kept", False)]:
        token = await repository.find_by_access_hash(f"access-{suffix}")
        await session.refresh(token)
        assert (token.revoked_at is not None) is revoked


async def test_the_service_rotates_and_detects_reuse_end_to_end(session: AsyncSession) -> None:
    user = await _add_user_and_client(session)
    service = OAuthTokenService(OAuthTokenRepository(session), LIFETIMES)
    first = await service.issue(user.id, CLIENT_ID)
    second = await service.refresh(first.refresh_token, CLIENT_ID)

    with pytest.raises(InvalidGrantError, match="reused"):
        await service.refresh(first.refresh_token, CLIENT_ID)

    with pytest.raises(InvalidGrantError, match="revoked"):
        await service.refresh(second.refresh_token, CLIENT_ID)
    revoked_row = await OAuthTokenRepository(session).find_by_access_hash(hash_secret(second.access_token))
    await session.refresh(revoked_row)
    assert revoked_row.revoked_at is not None
