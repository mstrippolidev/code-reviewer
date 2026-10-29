"""
    Tests for ApiTokenVerifier against a fake api/ served through httpx.MockTransport.
"""
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from mcp_server.custom_token_verification import CURRENT_USER_PATH, ApiTokenVerifier, TokenVerificationUnavailable

USER_ID = 5


def _verifier(handler: Callable[[httpx.Request], httpx.Response]) -> ApiTokenVerifier:
    client = httpx.AsyncClient(base_url="http://api", transport=httpx.MockTransport(handler))
    return ApiTokenVerifier(client)


@pytest.mark.asyncio
async def test_a_token_api_accepts_becomes_an_access_token_for_that_user() -> None:
    verifier = _verifier(lambda _request: httpx.Response(200, json={"id": USER_ID, "github_username": "someone"}))

    access_token = await verifier.verify_token("good-token")

    assert access_token is not None
    assert access_token.token == "good-token"
    assert access_token.subject == str(USER_ID)


@pytest.mark.asyncio
async def test_the_token_is_sent_to_api_as_a_bearer_on_the_current_user_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": USER_ID})

    await _verifier(handler).verify_token("good-token")

    [request] = seen
    assert request.url.path == CURRENT_USER_PATH
    assert request.headers["authorization"] == "Bearer good-token"


@pytest.mark.asyncio
async def test_a_token_api_rejects_is_not_an_access_token() -> None:
    verifier = _verifier(lambda _request: httpx.Response(401, json={"detail": "Invalid or expired access token"}))

    assert await verifier.verify_token("bad-token") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [403, 404, 500, 503])
async def test_an_unexpected_api_answer_is_an_error_not_a_rejection(status_code: int) -> None:
    verifier = _verifier(lambda _request: httpx.Response(status_code))

    with pytest.raises(TokenVerificationUnavailable, match=str(status_code)):
        await verifier.verify_token("any-token")


@pytest.mark.asyncio
async def test_an_unreachable_api_is_an_error_not_a_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(TokenVerificationUnavailable, match="unreachable"):
        await _verifier(handler).verify_token("any-token")


@pytest.mark.asyncio
async def test_a_current_user_payload_without_an_id_is_an_error() -> None:
    verifier = _verifier(lambda _request: httpx.Response(200, json={"github_username": "someone"}))

    with pytest.raises(ValidationError):
        await verifier.verify_token("any-token")
