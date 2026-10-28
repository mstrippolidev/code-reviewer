"""
    Tests for OAuthClientService against the real local Postgres, inside a rolled-back transaction.

    Requires the migrations to have been applied (`alembic upgrade head`).
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.oauth_consent import OAuthConsent
from api.db.models.user import User
from api.oauth.client_service import ClientRegistrationRequest, OAuthClientService
from api.oauth.errors import UnknownClientError

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

USER_GITHUB_ID = 960_000_001


async def _user(session: AsyncSession) -> User:
    user = User(
        github_id=USER_GITHUB_ID,
        github_username="oauth-client-test",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    await session.flush()
    return user


async def _register(service: OAuthClientService) -> str:
    request = ClientRegistrationRequest(client_name="Test", redirect_uris=["http://localhost:1/cb"])
    return (await service.register(request)).client_id


async def test_a_registered_client_round_trips_through_the_database(async_session: AsyncSession) -> None:
    service = OAuthClientService(async_session)
    client_id = await _register(service)
    async_session.expunge_all()

    client = await service.get(client_id)

    assert (client.client_name, client.redirect_uris) == ("Test", ["http://localhost:1/cb"])


async def test_an_unregistered_client_is_unknown(async_session: AsyncSession) -> None:
    with pytest.raises(UnknownClientError):
        await OAuthClientService(async_session).get("never-registered")


async def test_recording_consent_twice_leaves_one_row(async_session: AsyncSession) -> None:
    service = OAuthClientService(async_session)
    user, client_id = await _user(async_session), await _register(OAuthClientService(async_session))

    await service.record_consent(user.id, client_id)
    await service.record_consent(user.id, client_id)

    count = await async_session.scalar(select(func.count()).select_from(OAuthConsent))
    assert count == 1
    assert await service.has_consent(user.id, client_id)


async def test_consent_belongs_to_one_user_and_one_client(async_session: AsyncSession) -> None:
    service = OAuthClientService(async_session)
    user, client_id = await _user(async_session), await _register(service)
    other_client_id = await _register(service)

    await service.record_consent(user.id, client_id)

    assert not await service.has_consent(user.id, other_client_id)
    assert not await service.has_consent(user.id + 1, client_id)
