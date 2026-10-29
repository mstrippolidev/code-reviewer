"""
    Tests for CallerBearerAuth: the calling client's own token goes to api/ on every request, never a shared one.

    The SDK's auth context is set by hand, the way its middleware sets it for a real request.
"""
import asyncio
from collections.abc import Iterator

import httpx
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from mcp_server.custom_caller_auth import CallerBearerAuth, MissingCallerTokenError


def _authenticated_as(token: str) -> AuthenticatedUser:
    return AuthenticatedUser(AccessToken(token=token, client_id="api", scopes=[]))


def _echo_authorization(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"authorization": request.headers.get("authorization")})


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="http://api", transport=httpx.MockTransport(_echo_authorization), auth=CallerBearerAuth()
    )


@pytest.fixture(autouse=True)
def no_caller() -> Iterator[None]:
    context_token = auth_context_var.set(None)
    yield
    auth_context_var.reset(context_token)


@pytest.mark.asyncio
async def test_the_callers_token_is_sent_to_api_as_a_bearer() -> None:
    auth_context_var.set(_authenticated_as("caller-token"))

    response = await _client().get("/anything")

    assert response.json() == {"authorization": "Bearer caller-token"}


@pytest.mark.asyncio
async def test_a_call_outside_an_authenticated_request_is_refused() -> None:
    with pytest.raises(MissingCallerTokenError):
        await _client().get("/anything")


@pytest.mark.asyncio
async def test_a_header_already_on_the_request_does_not_survive() -> None:
    auth_context_var.set(_authenticated_as("caller-token"))

    response = await _client().get("/anything", headers={"Authorization": "Bearer someone-elses"})

    assert response.json() == {"authorization": "Bearer caller-token"}


@pytest.mark.asyncio
async def test_concurrent_callers_each_send_their_own_token() -> None:
    client = _client()

    async def call_as(token: str) -> str:
        auth_context_var.set(_authenticated_as(token))
        await asyncio.sleep(0)
        return (await client.get("/anything")).json()["authorization"]

    results = await asyncio.gather(*(call_as(f"token-{number}") for number in range(5)))

    assert results == [f"Bearer token-{number}" for number in range(5)]
