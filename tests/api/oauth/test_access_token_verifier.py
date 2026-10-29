"""
    Tests for OAuthAccessTokenVerifier against an in-memory repository and a controllable clock.

    Tokens are issued by the real OAuthTokenService so the verifier sees exactly the rows production writes.
"""
import pytest

from api.oauth.access_token_verifier import OAuthAccessTokenVerifier
from api.oauth.errors import InvalidOAuthAccessTokenError
from api.oauth.token_service import IssuedTokens, OAuthTokenService, TokenLifetimes
from tests.api.oauth.fakes import FakeClock, FakeTokenRepository

USER_ID = 7
CLIENT_ID = "client-a"
ACCESS_SECONDS = 3600

LIFETIMES = TokenLifetimes(
    access_seconds=ACCESS_SECONDS,
    refresh_idle_seconds=7 * 24 * 3600,
    refresh_absolute_seconds=30 * 24 * 3600,
)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repository() -> FakeTokenRepository:
    return FakeTokenRepository()


@pytest.fixture
def service(repository: FakeTokenRepository, clock: FakeClock) -> OAuthTokenService:
    return OAuthTokenService(repository, LIFETIMES, clock)


@pytest.fixture
def verifier(repository: FakeTokenRepository, clock: FakeClock) -> OAuthAccessTokenVerifier:
    return OAuthAccessTokenVerifier(repository, clock)


async def _issue(service: OAuthTokenService) -> IssuedTokens:
    return await service.issue(USER_ID, CLIENT_ID)


@pytest.mark.asyncio
async def test_a_live_access_token_resolves_to_its_user(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier
) -> None:
    tokens = await _issue(service)

    assert await verifier.verify(tokens.access_token) == USER_ID


@pytest.mark.asyncio
async def test_an_unknown_token_is_rejected(verifier: OAuthAccessTokenVerifier) -> None:
    with pytest.raises(InvalidOAuthAccessTokenError, match="unknown"):
        await verifier.verify("not-a-token")


@pytest.mark.asyncio
async def test_a_refresh_token_is_not_accepted_as_an_access_token(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier
) -> None:
    tokens = await _issue(service)

    with pytest.raises(InvalidOAuthAccessTokenError, match="unknown"):
        await verifier.verify(tokens.refresh_token)


@pytest.mark.asyncio
async def test_a_token_is_valid_until_the_second_before_it_expires(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    clock.advance(seconds=ACCESS_SECONDS - 1)

    assert await verifier.verify(tokens.access_token) == USER_ID


@pytest.mark.asyncio
async def test_a_token_is_rejected_at_its_expiry_instant(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    clock.advance(seconds=ACCESS_SECONDS)

    with pytest.raises(InvalidOAuthAccessTokenError, match="expired"):
        await verifier.verify(tokens.access_token)


@pytest.mark.asyncio
async def test_a_revoked_family_rejects_its_access_token(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier
) -> None:
    tokens = await _issue(service)
    await service.revoke(tokens.refresh_token)

    with pytest.raises(InvalidOAuthAccessTokenError, match="revoked"):
        await verifier.verify(tokens.access_token)


@pytest.mark.asyncio
async def test_revoking_a_family_after_a_refresh_rejects_the_newest_access_token(
    service: OAuthTokenService, verifier: OAuthAccessTokenVerifier
) -> None:
    first = await _issue(service)
    second = await service.refresh(first.refresh_token, CLIENT_ID)

    await service.revoke(first.refresh_token)

    with pytest.raises(InvalidOAuthAccessTokenError, match="revoked"):
        await verifier.verify(second.access_token)
