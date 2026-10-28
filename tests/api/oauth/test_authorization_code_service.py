"""
    Tests for AuthorizationCodeService rules against an in-memory Redis stand-in.
"""
import logging

import pytest

from api.oauth.authorization_code_service import AuthorizationCodeGrant, AuthorizationCodeService, CodeRedemption
from api.oauth.errors import InvalidGrantError
from tests.api.oauth.fakes import FakeRedis

USER_ID = 7
CLIENT_ID = "client-a"
REDIRECT_URI = "http://localhost:1234/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
TTL_SECONDS = 60


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def service(redis: FakeRedis) -> AuthorizationCodeService:
    return AuthorizationCodeService(redis, TTL_SECONDS)


def _grant() -> AuthorizationCodeGrant:
    return AuthorizationCodeGrant(
        user_id=USER_ID, client_id=CLIENT_ID, redirect_uri=REDIRECT_URI, code_challenge=CHALLENGE
    )


def _redemption(**overrides: str) -> CodeRedemption:
    fields = {"client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "code_verifier": VERIFIER} | overrides
    return CodeRedemption(**fields)


@pytest.mark.asyncio
async def test_a_valid_code_redeems_to_the_user_it_was_issued_for(service: AuthorizationCodeService) -> None:
    code = await service.issue(_grant())

    assert await service.redeem(code, _redemption()) == USER_ID


@pytest.mark.asyncio
async def test_a_code_works_only_once(service: AuthorizationCodeService) -> None:
    code = await service.issue(_grant())
    await service.redeem(code, _redemption())

    with pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption())


@pytest.mark.asyncio
async def test_an_unknown_code_is_rejected(service: AuthorizationCodeService) -> None:
    with pytest.raises(InvalidGrantError, match="unknown"):
        await service.redeem("never-issued", _redemption())


@pytest.mark.asyncio
async def test_each_issued_code_is_different(service: AuthorizationCodeService) -> None:
    assert await service.issue(_grant()) != await service.issue(_grant())


@pytest.mark.asyncio
async def test_the_code_expires_after_the_configured_ttl(
    service: AuthorizationCodeService, redis: FakeRedis
) -> None:
    await service.issue(_grant())

    assert list(redis.expiries.values()) == [TTL_SECONDS]


@pytest.mark.asyncio
async def test_the_raw_code_is_never_stored(service: AuthorizationCodeService, redis: FakeRedis) -> None:
    code = await service.issue(_grant())

    assert all(code not in key for key in redis.values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_id": "client-b"},
        {"redirect_uri": "http://localhost:9999/callback"},
        {"code_verifier": "x" * 43},
        {"code_verifier": "short"},
    ],
    ids=["client", "redirect-uri", "verifier", "malformed-verifier"],
)
@pytest.mark.asyncio
async def test_a_mismatched_redemption_is_rejected(service: AuthorizationCodeService, overrides: dict) -> None:
    code = await service.issue(_grant())

    with pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption(**overrides))


@pytest.mark.asyncio
async def test_a_failed_attempt_still_burns_the_code(service: AuthorizationCodeService) -> None:
    code = await service.issue(_grant())
    with pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption(code_verifier="x" * 43))

    with pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption())


@pytest.mark.asyncio
async def test_a_rejection_is_logged_with_its_reason_and_without_the_code(
    service: AuthorizationCodeService, caplog: pytest.LogCaptureFixture
) -> None:
    code = await service.issue(_grant())

    with caplog.at_level(logging.WARNING), pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption(client_id="client-b"))

    assert "another client" in caplog.text
    assert code not in caplog.text
