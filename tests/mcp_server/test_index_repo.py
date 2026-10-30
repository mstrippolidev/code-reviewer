import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.tools.index_repo import REGISTER_REPO_PATH, IndexRepoTool
from mcp_server.tools.repo_status import RepoState, RepoStatus, RepoStatusUnavailable

REPO = "acme/api"
API_BASE_URL = "http://api.test"

Handler = Callable[[httpx.Request], httpx.Response]
ToolFactory = Callable[..., IndexRepoTool]


class StubRepoStatusSource:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    async def fetch(self, repo: str) -> RepoStatus:
        if self._error:
            raise self._error
        return RepoStatus(
            state=RepoState.INDEXING,
            files_total=12,
            files_indexed=0,
            files_failed=0,
            indexed_commit=None,
            head_commit=None,
            branch="main",
        )


@pytest_asyncio.fixture
async def make_tool() -> AsyncIterator[ToolFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(handler: Handler, status_source: StubRepoStatusSource | None = None) -> IndexRepoTool:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(handler))
        clients.append(client)
        return IndexRepoTool(client, status_source or StubRepoStatusSource())

    yield build

    for client in clients:
        await client.aclose()


def accept_registration(request: httpx.Request) -> httpx.Response:
    return httpx.Response(201, json={})


def respond_with_status(
    status_code: int, detail: str | None = None, headers: dict[str, str] | None = None
) -> Handler:
    body = {"detail": detail} if detail else None
    return lambda request: httpx.Response(status_code, json=body, headers=headers)


def fail_to_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def record_into(requests: list[httpx.Request]) -> Handler:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json={})

    return record


@pytest.mark.asyncio
async def test_index_repo_posts_to_the_repo_registration_path(make_tool: ToolFactory) -> None:
    """Verify that indexing goes through api/'s registration endpoint."""
    requests: list[httpx.Request] = []

    await make_tool(record_into(requests)).index_repo(REPO)

    assert (requests[0].method, requests[0].url.path) == ("POST", REGISTER_REPO_PATH)


@pytest.mark.asyncio
async def test_index_repo_sends_the_full_name_and_the_requested_branch(make_tool: ToolFactory) -> None:
    """Verify that api/ receives the repo name, not an id, together with the branch asked for."""
    requests: list[httpx.Request] = []

    await make_tool(record_into(requests)).index_repo(REPO, "dev")

    assert json.loads(requests[0].content) == {"full_name": REPO, "branch": "dev"}


@pytest.mark.asyncio
async def test_index_repo_without_a_branch_sends_null_so_api_uses_the_default(make_tool: ToolFactory) -> None:
    """Verify that an omitted branch reaches api/ as null, which selects the repo's default branch."""
    requests: list[httpx.Request] = []

    await make_tool(record_into(requests)).index_repo(REPO)

    assert json.loads(requests[0].content)["branch"] is None


@pytest.mark.asyncio
async def test_index_repo_returns_the_status_snapshot(make_tool: ToolFactory) -> None:
    """Verify that the caller gets the repo's index state back right after registering."""
    status = await make_tool(accept_registration).index_repo(REPO)

    assert status.state == RepoState.INDEXING


@pytest.mark.parametrize(
    "status_code,detail,expected_text",
    [
        (400, "Branch 'mian' was not found", "Branch 'mian' was not found"),
        (400, "Branch 'mian' was not found", "call index_repo again"),
        (401, None, "sign in again"),
        (404, None, "owner/name spelling"),
        (429, "You already have 3 repos being indexed", "You already have 3 repos being indexed"),
        (429, "You already have 3 repos being indexed", "get_repo_status"),
        (500, None, "Try again shortly"),
        (502, None, "api/ answered 502"),
    ],
)
@pytest.mark.asyncio
async def test_index_repo_turns_an_api_refusal_into_a_tool_error_naming_the_next_step(
    make_tool: ToolFactory, status_code: int, detail: str | None, expected_text: str
) -> None:
    """Verify that each refusal from api/ tells the calling LLM what happened and what to do next."""
    tool = make_tool(respond_with_status(status_code, detail))

    with pytest.raises(ToolError, match=expected_text):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_for_an_unknown_repo_names_the_repo_in_the_error(make_tool: ToolFactory) -> None:
    """Verify that the not-found error repeats the repo so a typo is easy to spot."""
    tool = make_tool(respond_with_status(404))

    with pytest.raises(ToolError, match=REPO):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_when_rate_limited_reports_how_long_to_wait(make_tool: ToolFactory) -> None:
    """Verify that the Retry-After from api/ reaches the LLM so it does not retry at once."""
    tool = make_tool(respond_with_status(429, "Too many requests", {"Retry-After": "30"}))

    with pytest.raises(ToolError, match="Retry after 30 seconds"):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_when_refused_without_a_readable_reason_still_explains_itself(
    make_tool: ToolFactory,
) -> None:
    """Verify that a 400 with no JSON detail does not leak a raw body or crash the error path."""
    tool = make_tool(lambda request: httpx.Response(400, text="<html>bad</html>"))

    with pytest.raises(ToolError, match="api/ refused the request"):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_does_not_double_the_full_stop_of_an_api_detail(make_tool: ToolFactory) -> None:
    """Verify that a detail already ending in a full stop is not followed by a second one."""
    tool = make_tool(respond_with_status(400, "Repo is too small."))

    with pytest.raises(ToolError) as raised:
        await tool.index_repo(REPO)

    assert ".." not in str(raised.value)


@pytest.mark.asyncio
async def test_index_repo_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure surfaces as a ToolError, not a raw httpx error."""
    tool = make_tool(fail_to_connect)

    with pytest.raises(ToolError, match="unreachable"):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_when_the_status_cannot_be_read_says_the_repo_was_registered(
    make_tool: ToolFactory,
) -> None:
    """Verify that a failed status read after a successful registration is not reported as a failed registration."""
    unreadable = StubRepoStatusSource(error=RepoStatusUnavailable("api/ answered 500"))
    tool = make_tool(accept_registration, unreadable)

    with pytest.raises(ToolError, match="was registered"):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_when_the_status_cannot_be_read_points_to_get_repo_status(
    make_tool: ToolFactory,
) -> None:
    """Verify that the error names the tool to call next."""
    unreadable = StubRepoStatusSource(error=RepoStatusUnavailable("api/ answered 500"))
    tool = make_tool(accept_registration, unreadable)

    with pytest.raises(ToolError, match="get_repo_status"):
        await tool.index_repo(REPO)


@pytest.mark.asyncio
async def test_index_repo_does_not_read_the_status_when_registration_is_refused(make_tool: ToolFactory) -> None:
    """Verify that a refused registration stops before asking for a status."""
    unreadable = StubRepoStatusSource(error=RepoStatusUnavailable("must not be called"))
    tool = make_tool(respond_with_status(404), unreadable)

    with pytest.raises(ToolError, match="not found"):
        await tool.index_repo(REPO)


@pytest.fixture
def server(make_tool: ToolFactory) -> MCPServer:
    mcp = MCPServer("test")
    mcp.add_tool(make_tool(respond_with_status(404)).index_repo)
    return mcp


@pytest.mark.asyncio
async def test_index_repo_refusal_is_flagged_as_a_tool_error_to_the_client(server: MCPServer) -> None:
    """Verify that the calling LLM sees is_error, which tells it to change course."""
    async with Client(server) as client:
        result = await client.call_tool("index_repo", {"repo_full_name": REPO})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_index_repo_is_described_for_the_calling_llm(server: MCPServer) -> None:
    """Verify that the tool ships a description, the model's only documentation."""
    async with Client(server) as client:
        result = await client.list_tools()

    assert result.tools[0].description


@pytest.mark.asyncio
async def test_index_repo_description_explains_both_parameters_to_the_calling_llm(server: MCPServer) -> None:
    """Verify that the description names each argument, since the SDK ships the docstring's Args there."""
    async with Client(server) as client:
        result = await client.list_tools()

    description = result.tools[0].description
    assert "repo_full_name:" in description and "branch_name:" in description
