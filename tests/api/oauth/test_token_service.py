"""
    Tests for OAuthTokenService rules against an in-memory repository and a controllable clock.
"""
import logging
from datetime import timedelta

import pytest

from api.oauth.errors import InvalidGrantError
from api.oauth.token_secrets import hash_secret
from api.oauth.token_service import IssuedTokens, OAuthTokenService, TokenLifetimes
from tests.api.oauth.fakes import START, FakeClock, FakeTokenRepository

USER_ID = 7
CLIENT_ID = "client-a"
OTHER_CLIENT_ID = "client-b"

LIFETIMES = TokenLifetimes(
    access_seconds=3600,
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


async def _issue(service: OAuthTokenService) -> IssuedTokens:
    return await service.issue(USER_ID, CLIENT_ID)


@pytest.mark.asyncio
async def test_issue_stores_only_the_hashes(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    tokens = await _issue(service)

    [row] = repository.rows
    assert row.access_token_hash == hash_secret(tokens.access_token)
    assert row.refresh_token_hash == hash_secret(tokens.refresh_token)
    assert tokens.access_token not in vars(row).values()
    assert tokens.refresh_token not in vars(row).values()


@pytest.mark.asyncio
async def test_issue_binds_the_row_to_the_user_and_client(
    service: OAuthTokenService, repository: FakeTokenRepository
) -> None:
    await _issue(service)

    [row] = repository.rows
    assert (row.user_id, row.client_id) == (USER_ID, CLIENT_ID)


@pytest.mark.asyncio
async def test_issue_sets_the_configured_expiries(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    tokens = await _issue(service)

    [row] = repository.rows
    assert row.access_expires_at == START + timedelta(hours=1)
    assert row.refresh_expires_at == START + timedelta(days=7)
    assert row.authorized_at == START
    assert tokens.expires_in == 3600


@pytest.mark.asyncio
async def test_each_issue_starts_a_new_family(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    await _issue(service)
    await _issue(service)

    assert repository.rows[0].family_id != repository.rows[1].family_id


@pytest.mark.asyncio
async def test_issue_commits(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    await _issue(service)

    assert repository.commits == 1


@pytest.mark.asyncio
async def test_refresh_returns_a_new_pair_and_uses_up_the_old_refresh_token(
    service: OAuthTokenService, repository: FakeTokenRepository, clock: FakeClock
) -> None:
    first = await _issue(service)
    clock.advance(hours=2)

    second = await service.refresh(first.refresh_token, CLIENT_ID)

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert repository.rows[0].refresh_used_at == clock.now
    assert len(repository.rows) == 2


@pytest.mark.asyncio
async def test_refresh_keeps_the_family_and_the_original_authorization_time(
    service: OAuthTokenService, repository: FakeTokenRepository, clock: FakeClock
) -> None:
    first = await _issue(service)
    clock.advance(days=3)

    await service.refresh(first.refresh_token, CLIENT_ID)

    old, new = repository.rows
    assert new.family_id == old.family_id
    assert new.authorized_at == START
    assert (new.user_id, new.client_id) == (USER_ID, CLIENT_ID)


@pytest.mark.asyncio
async def test_refresh_restarts_the_idle_window(
    service: OAuthTokenService, repository: FakeTokenRepository, clock: FakeClock
) -> None:
    first = await _issue(service)
    clock.advance(days=6)

    await service.refresh(first.refresh_token, CLIENT_ID)

    assert repository.rows[1].refresh_expires_at == clock.now + timedelta(days=7)


@pytest.mark.asyncio
async def test_a_refresh_token_unused_for_the_idle_period_is_rejected(
    service: OAuthTokenService, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    clock.advance(days=7)

    with pytest.raises(InvalidGrantError, match="expired"):
        await service.refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_a_rejected_expired_refresh_is_not_marked_used(
    service: OAuthTokenService, repository: FakeTokenRepository, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    clock.advance(days=8)

    with pytest.raises(InvalidGrantError):
        await service.refresh(tokens.refresh_token, CLIENT_ID)

    assert repository.rows[0].refresh_used_at is None


@pytest.mark.asyncio
async def test_a_refresh_just_inside_the_idle_period_is_accepted(
    service: OAuthTokenService, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    clock.advance(days=6, hours=23)

    assert await service.refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_daily_use_cannot_extend_the_authorization_past_the_absolute_lifetime(
    service: OAuthTokenService, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    for _ in range(29):
        clock.advance(days=1)
        tokens = await service.refresh(tokens.refresh_token, CLIENT_ID)
    clock.advance(days=1)

    with pytest.raises(InvalidGrantError, match="expired"):
        await service.refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_a_refresh_token_never_claims_to_outlive_the_absolute_lifetime(
    service: OAuthTokenService, repository: FakeTokenRepository, clock: FakeClock
) -> None:
    tokens = await _issue(service)
    for _ in range(4):
        clock.advance(days=6)
        tokens = await service.refresh(tokens.refresh_token, CLIENT_ID)
    clock.advance(days=2)

    await service.refresh(tokens.refresh_token, CLIENT_ID)

    assert repository.rows[-1].refresh_expires_at == START + timedelta(days=30)


@pytest.mark.asyncio
async def test_shortening_the_absolute_lifetime_applies_to_tokens_already_issued(
    repository: FakeTokenRepository, clock: FakeClock
) -> None:
    tokens = await OAuthTokenService(repository, LIFETIMES, clock).issue(USER_ID, CLIENT_ID)
    shortened = LIFETIMES.model_copy(update={"refresh_absolute_seconds": 2 * 24 * 3600})
    clock.advance(days=3)

    with pytest.raises(InvalidGrantError, match="absolute"):
        await OAuthTokenService(repository, shortened, clock).refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_an_unknown_refresh_token_is_rejected(service: OAuthTokenService) -> None:
    with pytest.raises(InvalidGrantError, match="unknown"):
        await service.refresh("never-issued", CLIENT_ID)


@pytest.mark.asyncio
async def test_an_access_token_is_not_accepted_as_a_refresh_token(service: OAuthTokenService) -> None:
    tokens = await _issue(service)

    with pytest.raises(InvalidGrantError):
        await service.refresh(tokens.access_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_a_refresh_token_cannot_be_used_by_another_client(
    service: OAuthTokenService, repository: FakeTokenRepository
) -> None:
    tokens = await _issue(service)

    with pytest.raises(InvalidGrantError, match="another client"):
        await service.refresh(tokens.refresh_token, OTHER_CLIENT_ID)

    assert repository.rows[0].refresh_used_at is None


@pytest.mark.asyncio
async def test_a_revoked_refresh_token_is_rejected(service: OAuthTokenService) -> None:
    tokens = await _issue(service)
    await service.revoke(tokens.refresh_token)

    with pytest.raises(InvalidGrantError, match="revoked"):
        await service.refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_reusing_an_old_refresh_token_revokes_the_whole_family(
    service: OAuthTokenService, repository: FakeTokenRepository
) -> None:
    first = await _issue(service)
    second = await service.refresh(first.refresh_token, CLIENT_ID)

    with pytest.raises(InvalidGrantError, match="reused"):
        await service.refresh(first.refresh_token, CLIENT_ID)

    assert all(row.revoked_at is not None for row in repository.rows)
    with pytest.raises(InvalidGrantError, match="revoked"):
        await service.refresh(second.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_reuse_revocation_is_committed_before_the_error_is_raised(
    service: OAuthTokenService, repository: FakeTokenRepository
) -> None:
    first = await _issue(service)
    await service.refresh(first.refresh_token, CLIENT_ID)
    commits_before = repository.commits

    with pytest.raises(InvalidGrantError):
        await service.refresh(first.refresh_token, CLIENT_ID)

    assert repository.commits == commits_before + 1


@pytest.mark.asyncio
async def test_reuse_revokes_only_its_own_family(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    first = await _issue(service)
    bystander = await _issue(service)
    await service.refresh(first.refresh_token, CLIENT_ID)

    with pytest.raises(InvalidGrantError):
        await service.refresh(first.refresh_token, CLIENT_ID)

    assert repository.rows[1].revoked_at is None
    assert await service.refresh(bystander.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_losing_the_concurrent_use_race_is_treated_as_reuse(
    service: OAuthTokenService, repository: FakeTokenRepository
) -> None:
    tokens = await _issue(service)
    repository.lose_the_race = True

    with pytest.raises(InvalidGrantError, match="concurrently"):
        await service.refresh(tokens.refresh_token, CLIENT_ID)

    assert repository.rows[0].revoked_at is not None
    assert len(repository.rows) == 1


@pytest.mark.asyncio
async def test_revoking_the_access_token_revokes_the_family(service: OAuthTokenService) -> None:
    tokens = await _issue(service)

    await service.revoke(tokens.access_token)

    with pytest.raises(InvalidGrantError):
        await service.refresh(tokens.refresh_token, CLIENT_ID)


@pytest.mark.asyncio
async def test_revoking_an_unknown_token_is_silent(service: OAuthTokenService, repository: FakeTokenRepository) -> None:
    await service.revoke("never-issued")

    assert repository.commits == 0


@pytest.mark.asyncio
async def test_a_rejection_is_logged_with_its_reason_and_without_the_token(
    service: OAuthTokenService, caplog: pytest.LogCaptureFixture
) -> None:
    tokens = await _issue(service)

    with caplog.at_level(logging.WARNING), pytest.raises(InvalidGrantError):
        await service.refresh(tokens.refresh_token, OTHER_CLIENT_ID)

    assert "belongs to another client" in caplog.text
    assert tokens.refresh_token not in caplog.text
