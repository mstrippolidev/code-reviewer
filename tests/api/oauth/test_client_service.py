"""
    Tests for OAuthClientService against an in-memory session.
"""
import pytest
from pydantic import ValidationError

from api.oauth.client_service import ClientRegistrationRequest, OAuthClientService
from api.oauth.errors import InvalidRedirectUriError, UnknownClientError
from tests.api.oauth.fakes import FakeOAuthSession

REDIRECT_URI = "http://localhost:1234/callback"


@pytest.fixture
def session() -> FakeOAuthSession:
    return FakeOAuthSession()


@pytest.fixture
def service(session: FakeOAuthSession) -> OAuthClientService:
    return OAuthClientService(session)


def _request(**overrides) -> ClientRegistrationRequest:
    fields = {"client_name": "Claude Code", "redirect_uris": [REDIRECT_URI]} | overrides
    return ClientRegistrationRequest(**fields)


@pytest.mark.asyncio
async def test_registering_stores_a_client_with_a_fresh_id(service: OAuthClientService, session: FakeOAuthSession) -> None:
    client = await service.register(_request())

    assert session.clients[client.client_id] is client
    assert session.commits == 1
    assert len(client.client_id) >= 32


@pytest.mark.asyncio
async def test_two_registrations_get_different_ids(service: OAuthClientService) -> None:
    assert (await service.register(_request())).client_id != (await service.register(_request())).client_id


@pytest.mark.asyncio
async def test_duplicate_redirect_uris_are_stored_once(service: OAuthClientService) -> None:
    client = await service.register(_request(redirect_uris=[REDIRECT_URI, REDIRECT_URI]))

    assert client.redirect_uris == [REDIRECT_URI]


@pytest.mark.asyncio
async def test_an_invalid_redirect_uri_stores_nothing(service: OAuthClientService, session: FakeOAuthSession) -> None:
    with pytest.raises(InvalidRedirectUriError):
        await service.register(_request(redirect_uris=[REDIRECT_URI, "http://evil.example.com/cb"]))

    assert session.clients == {}
    assert session.commits == 0


def test_the_client_name_is_trimmed() -> None:
    assert _request(client_name="  Cursor  ").client_name == "Cursor"


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_a_missing_or_oversized_client_name_is_rejected(name: str) -> None:
    with pytest.raises(ValidationError):
        _request(client_name=name)


@pytest.mark.parametrize("uris", [[], [REDIRECT_URI] * 6])
def test_zero_or_too_many_redirect_uris_are_rejected(uris: list[str]) -> None:
    with pytest.raises(ValidationError):
        _request(redirect_uris=uris)


def test_unknown_registration_fields_are_ignored() -> None:
    request = _request(token_endpoint_auth_method="client_secret_basic", logo_uri="https://x")

    assert request.client_name == "Claude Code"


@pytest.mark.asyncio
async def test_a_registered_client_can_be_fetched(service: OAuthClientService) -> None:
    client = await service.register(_request())

    assert await service.get(client.client_id) is client


@pytest.mark.asyncio
async def test_an_unknown_client_raises(service: OAuthClientService) -> None:
    with pytest.raises(UnknownClientError):
        await service.get("never-registered")


@pytest.mark.asyncio
async def test_consent_is_absent_until_recorded_and_is_per_user_and_client(service: OAuthClientService) -> None:
    assert not await service.has_consent(1, "client-a")

    await service.record_consent(1, "client-a")

    assert await service.has_consent(1, "client-a")
    assert not await service.has_consent(2, "client-a")
    assert not await service.has_consent(1, "client-b")


@pytest.mark.asyncio
async def test_recording_consent_twice_is_harmless(service: OAuthClientService) -> None:
    await service.record_consent(1, "client-a")
    await service.record_consent(1, "client-a")

    assert await service.has_consent(1, "client-a")
