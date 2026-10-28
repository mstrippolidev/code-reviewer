"""
    Tests for AuthorizationCodeService against the real local Redis (REDIS_URL).

    Each test deletes the keys it created. Run with `-m redis`.
"""
import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from api.config.settings import get_api_settings
from api.oauth.authorization_code_service import (
    CODE_KEY_PREFIX,
    AuthorizationCodeGrant,
    AuthorizationCodeService,
    CodeRedemption,
)
from api.oauth.errors import InvalidGrantError
from api.oauth.token_secrets import hash_secret

pytestmark = [pytest.mark.redis, pytest.mark.asyncio]

CLIENT_ID = "redis-test-client"
REDIRECT_URI = "http://localhost:1234/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
TTL_SECONDS = 60


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_api_settings().redis_url)
    yield client
    await client.aclose()


def _grant() -> AuthorizationCodeGrant:
    return AuthorizationCodeGrant(user_id=7, client_id=CLIENT_ID, redirect_uri=REDIRECT_URI, code_challenge=CHALLENGE)


def _redemption() -> CodeRedemption:
    return CodeRedemption(client_id=CLIENT_ID, redirect_uri=REDIRECT_URI, code_verifier=VERIFIER)


def _key(code: str) -> str:
    return f"{CODE_KEY_PREFIX}:{hash_secret(code)}"


async def test_an_issued_code_has_a_ttl_no_longer_than_the_configured_one(redis: Redis) -> None:
    code = await AuthorizationCodeService(redis, TTL_SECONDS).issue(_grant())

    try:
        assert 0 < await redis.ttl(_key(code)) <= TTL_SECONDS
    finally:
        await redis.delete(_key(code))


async def test_redeeming_removes_the_code_from_redis(redis: Redis) -> None:
    service = AuthorizationCodeService(redis, TTL_SECONDS)
    code = await service.issue(_grant())

    assert await service.redeem(code, _redemption()) == 7
    assert await redis.exists(_key(code)) == 0


async def test_an_expired_code_is_rejected(redis: Redis) -> None:
    service = AuthorizationCodeService(redis, ttl_seconds=1)
    code = await service.issue(_grant())

    await asyncio.sleep(1.2)

    with pytest.raises(InvalidGrantError):
        await service.redeem(code, _redemption())


async def test_only_one_of_many_simultaneous_redemptions_wins(redis: Redis) -> None:
    service = AuthorizationCodeService(redis, TTL_SECONDS)
    code = await service.issue(_grant())

    results = await asyncio.gather(
        *(service.redeem(code, _redemption()) for _ in range(20)), return_exceptions=True
    )

    assert results.count(7) == 1
    assert sum(isinstance(result, InvalidGrantError) for result in results) == 19
