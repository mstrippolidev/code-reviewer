"""
    Tests for the MCP server's OAuth surface over the SDK's real streamable-HTTP app.

    The 401 challenge and the metadata document are checked on the real `mcp` instance. Token verification and
    forwarding are checked on a server wired the same way as mcp_server/app.py and server.py, with a fake api/.
"""
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from starlette.applications import Starlette

from mcp_server.app import mcp
from mcp_server.config import get_mcp_settings
from mcp_server.custom_caller_auth import CallerBearerAuth
from mcp_server.custom_token_verification import CURRENT_USER_PATH, ApiTokenVerifier

PUBLIC_URL = "http://localhost:8001"
PROTOCOL_VERSION = "2025-06-18"
JSON_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
USER_IDS_BY_TOKEN = {"token-a": 1, "token-b": 2}


class FakeApi:
    def __init__(self) -> None:
        self.authorizations: list[str | None] = []
        self.unreachable = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("connection refused", request=request)
        authorization = request.headers.get("authorization")
        self.authorizations.append(authorization)
        user_id = USER_IDS_BY_TOKEN.get((authorization or "").removeprefix("Bearer "))
        if user_id is None:
            return httpx.Response(401)
        return httpx.Response(200, json={"id": user_id})


def _build_server(api: FakeApi) -> MCPServer:
    transport = httpx.MockTransport(api.handle)
    verifier = ApiTokenVerifier(httpx.AsyncClient(base_url="http://api", transport=transport))
    forwarding_client = httpx.AsyncClient(base_url="http://api", transport=transport, auth=CallerBearerAuth())
    server = MCPServer(
        "Code-Review-Test",
        auth=AuthSettings(issuer_url="http://api", resource_server_url=PUBLIC_URL, validate_token_resource=False),
        token_verifier=verifier,
    )

    async def whoami() -> int:
        response = await forwarding_client.get(CURRENT_USER_PATH)
        return response.json()["id"]

    server.add_tool(whoami)
    return server


def _client_for(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=PUBLIC_URL)


@asynccontextmanager
async def _serving(api: FakeApi) -> AsyncIterator[httpx.AsyncClient]:
    app = _build_server(api).streamable_http_app(json_response=True)
    async with app.router.lifespan_context(app), _client_for(app) as client:
        yield client


@pytest.fixture(scope="module")
def real_app_client() -> httpx.AsyncClient:
    return _client_for(mcp.streamable_http_app(json_response=True))


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


async def _rpc(client: httpx.AsyncClient, headers: dict[str, str], payload: dict) -> httpx.Response:
    return await client.post("/mcp", json={"jsonrpc": "2.0", **payload}, headers=headers)


async def _open_session(client: httpx.AsyncClient, token: str) -> dict[str, str]:
    headers = JSON_HEADERS | {"Authorization": f"Bearer {token}"}
    initialize = {
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }
    response = await _rpc(client, headers, initialize)
    session_headers = headers | {"Mcp-Session-Id": response.headers["mcp-session-id"], "MCP-Protocol-Version": PROTOCOL_VERSION}
    await _rpc(client, session_headers, {"method": "notifications/initialized"})
    return session_headers


async def _call_whoami(client: httpx.AsyncClient, token: str) -> int:
    headers = await _open_session(client, token)
    response = await _rpc(client, headers, {"id": 2, "method": "tools/call", "params": {"name": "whoami", "arguments": {}}})
    return json.loads(response.text)["result"]["structuredContent"]["result"]


@pytest.mark.asyncio
async def test_a_request_without_a_token_gets_a_challenge_pointing_at_the_metadata(
    real_app_client: httpx.AsyncClient,
) -> None:
    response = await real_app_client.post("/mcp", json={}, headers=JSON_HEADERS)

    assert response.status_code == 401
    expected_url = f'resource_metadata="{get_mcp_settings().mcp_public_base_url}/.well-known/oauth-protected-resource"'
    assert expected_url in response.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_the_metadata_names_api_as_the_authorization_server(real_app_client: httpx.AsyncClient) -> None:
    response = await real_app_client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    assert response.json()["authorization_servers"] == [get_mcp_settings().mcp_authorization_server_url]


@pytest.mark.asyncio
async def test_a_token_api_rejects_gets_the_challenge(api: FakeApi) -> None:
    async with _serving(api) as client:
        response = await client.post("/mcp", json={}, headers=JSON_HEADERS | {"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]


@pytest.mark.asyncio
async def test_a_tool_call_reaches_api_as_the_caller(api: FakeApi) -> None:
    async with _serving(api) as client:
        assert await _call_whoami(client, "token-a") == USER_IDS_BY_TOKEN["token-a"]
    assert api.authorizations[-1] == "Bearer token-a"


@pytest.mark.asyncio
async def test_two_callers_are_each_served_as_themselves(api: FakeApi) -> None:
    async with _serving(api) as client:
        assert await _call_whoami(client, "token-a") == USER_IDS_BY_TOKEN["token-a"]
        assert await _call_whoami(client, "token-b") == USER_IDS_BY_TOKEN["token-b"]


@pytest.mark.asyncio
async def test_an_unreachable_api_fails_the_request_instead_of_challenging(api: FakeApi) -> None:
    api.unreachable = True

    async with _serving(api) as client:
        response = await client.post("/mcp", json={}, headers=JSON_HEADERS | {"Authorization": "Bearer token-a"})

    assert response.status_code == 500
