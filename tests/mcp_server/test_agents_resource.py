from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ResourceError

from mcp_server.resources.agents import AGENTS_PATH, AGENTS_URI, AgentsResource
from mcp_server.server import mcp

API_BASE_URL = "http://api.test"

Handler = Callable[[httpx.Request], httpx.Response]
ResourceFactory = Callable[[Handler], AgentsResource]


def agent_payload(code_key: str = "VAR", **overrides: Any) -> dict[str, Any]:
    payload = {
        "code_key": code_key,
        "name": "Naming",
        "weight": 1.0,
        "category": "chunk",
        "summary": "Expressive names.",
        "checks": ["no abbreviations"],
    }
    return payload | overrides


def respond_with(payload: Any) -> Handler:
    return lambda request: httpx.Response(200, json=payload)


def respond_with_status(status_code: int) -> Handler:
    return lambda request: httpx.Response(status_code, json={"detail": "internal path /srv/secret"})


def fail_to_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest_asyncio.fixture
async def make_resource() -> AsyncIterator[ResourceFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(handler: Handler) -> AgentsResource:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(handler))
        clients.append(client)
        return AgentsResource(client)

    yield build

    for client in clients:
        await client.aclose()


@pytest.mark.asyncio
async def test_read_agents_asks_api_for_the_agent_list(make_resource: ResourceFactory) -> None:
    """Verify that the resource reads the roster from api/'s agents endpoint."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[agent_payload()])

    await make_resource(record).read_agents()

    assert (requests[0].method, requests[0].url.path) == ("GET", AGENTS_PATH)


@pytest.mark.asyncio
async def test_read_agents_returns_every_agent_api_lists(make_resource: ResourceFactory) -> None:
    """Verify that no agent is dropped on the way to the calling LLM."""
    payload = [agent_payload("VAR"), agent_payload("TEST", name="Testability"), agent_payload("DRY")]

    agents = await make_resource(respond_with(payload)).read_agents()

    assert [agent.code_key for agent in agents] == ["VAR", "TEST", "DRY"]


@pytest.mark.asyncio
async def test_read_agents_keeps_what_each_agent_checks(make_resource: ResourceFactory) -> None:
    """Verify that the rubric text the LLM uses to pick agents survives unchanged."""
    payload = [agent_payload(checks=["no abbreviations", "consistent vocabulary"])]

    agents = await make_resource(respond_with(payload)).read_agents()

    assert agents[0].checks == ["no abbreviations", "consistent vocabulary"]


@pytest.mark.asyncio
async def test_read_agents_keeps_the_weight(make_resource: ResourceFactory) -> None:
    """Verify that the weight is exposed, since it tells the LLM how much an agent moves the rating."""
    agents = await make_resource(respond_with([agent_payload(weight=2.0)])).read_agents()

    assert agents[0].weight == 2.0


@pytest.mark.asyncio
async def test_read_agents_with_an_empty_roster_returns_an_empty_list(make_resource: ResourceFactory) -> None:
    """Verify that an empty roster is a valid answer and not an error."""
    agents = await make_resource(respond_with([])).read_agents()

    assert agents == []


@pytest.mark.parametrize("status_code", [401, 500, 502])
@pytest.mark.asyncio
async def test_read_agents_when_api_fails_tells_the_client_to_retry(
    make_resource: ResourceFactory, status_code: int
) -> None:
    """Verify that an api/ failure becomes a retry hint rather than a raw error."""
    with pytest.raises(ResourceError, match="Try again shortly"):
        await make_resource(respond_with_status(status_code)).read_agents()


@pytest.mark.asyncio
async def test_read_agents_when_api_fails_does_not_leak_the_api_error_body(make_resource: ResourceFactory) -> None:
    """Verify that internal details from api/ never reach the calling LLM."""
    with pytest.raises(ResourceError) as raised:
        await make_resource(respond_with_status(500)).read_agents()

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_read_agents_when_api_is_unreachable_reports_a_resource_error(make_resource: ResourceFactory) -> None:
    """Verify that a network failure surfaces as a ResourceError, not a raw httpx error."""
    with pytest.raises(ResourceError, match="unavailable"):
        await make_resource(fail_to_connect).read_agents()


@pytest.mark.asyncio
async def test_read_agents_when_the_body_is_not_json_reports_a_resource_error(make_resource: ResourceFactory) -> None:
    """Verify that a proxy error page returned with a 200 becomes a retry hint."""
    handler = lambda request: httpx.Response(200, content=b"<html>gateway</html>")

    with pytest.raises(ResourceError, match="could not be read"):
        await make_resource(handler).read_agents()


@pytest.mark.parametrize("missing_key", ["code_key", "name", "weight", "category", "summary", "checks"])
@pytest.mark.asyncio
async def test_read_agents_when_an_agent_omits_a_field_reports_a_resource_error(
    make_resource: ResourceFactory, missing_key: str
) -> None:
    """Verify that an agent missing a field does not escape as a raw validation error."""
    broken = agent_payload()
    del broken[missing_key]

    with pytest.raises(ResourceError, match="could not be read"):
        await make_resource(respond_with([broken])).read_agents()


@pytest.mark.asyncio
async def test_read_agents_when_the_body_is_not_a_list_reports_a_resource_error(make_resource: ResourceFactory) -> None:
    """Verify that a JSON object where a list was expected is reported, not iterated over its keys."""
    with pytest.raises(ResourceError, match="could not be read"):
        await make_resource(respond_with({"agents": []})).read_agents()


async def _listed_resource(uri: str) -> Any:
    async with Client(mcp) as client:
        result = await client.list_resources()
    return next(resource for resource in result.resources if str(resource.uri) == uri)


@pytest.mark.asyncio
async def test_server_lists_the_agents_resource() -> None:
    """Verify that connecting clients are told the agents resource exists."""
    resource = await _listed_resource(AGENTS_URI)

    assert resource.name == "agents"


@pytest.mark.asyncio
async def test_agents_resource_is_served_as_json() -> None:
    """Verify that clients are told to parse the agent list as JSON."""
    resource = await _listed_resource(AGENTS_URI)

    assert resource.mime_type == "application/json"


@pytest.mark.asyncio
async def test_agents_resource_description_warns_that_dry_needs_a_repo() -> None:
    """Verify that the LLM is told, before it picks agents, that a review with no repo skips DRY."""
    resource = await _listed_resource(AGENTS_URI)

    assert "skips it" in resource.description
