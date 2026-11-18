import httpx
import pytest

from mcp_server.health import HEALTH_PATH
from mcp_server.server import mcp


@pytest.fixture(scope="module")
def client() -> httpx.AsyncClient:
    """The real server's HTTP app, the one the pod runs."""
    app = mcp.streamable_http_app(json_response=True)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8001")


@pytest.mark.asyncio
async def test_health_answers_200_without_a_token(client: httpx.AsyncClient) -> None:
    """Verify that the kubelet, which holds no OAuth token, can probe the server.

    Every other route challenges an unauthenticated caller with a 401, which would fail the probe.
    """
    response = await client.get(HEALTH_PATH)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_reports_ok_in_the_body(client: httpx.AsyncClient) -> None:
    """Verify that the body says the server is serving, for the image's HEALTHCHECK and for humans."""
    response = await client.get(HEALTH_PATH)

    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_mcp_endpoint_still_challenges_a_caller_without_a_token(client: httpx.AsyncClient) -> None:
    """Verify that opening the health route did not open the MCP endpoint itself."""
    response = await client.post("/mcp", json={}, headers={"Accept": "application/json, text/event-stream"})

    assert response.status_code == 401
