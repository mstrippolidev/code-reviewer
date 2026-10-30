from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.server import MCPServer

from mcp_server.tools.repo_status import (
    HttpRepoStatusSource,
    RepoNotFound,
    RepoState,
    RepoStatus,
    RepoStatusTools,
    RepoStatusUnavailable,
)

KNOWN_REPO = "acme/api"
UNKNOWN_REPO = "nobody/nothing"
API_BASE_URL = "http://api.test"

Handler = Callable[[httpx.Request], httpx.Response]
SourceFactory = Callable[[Handler], HttpRepoStatusSource]


class StubRepoStatusSource:
    async def fetch(self, repo: str) -> RepoStatus:
        if repo != KNOWN_REPO:
            raise RepoNotFound(repo)
        return RepoStatus(
            state=RepoState.READY,
            files_total=10,
            files_indexed=10,
            files_failed=0,
            indexed_commit="abc123",
            head_commit="abc123",
            branch="main",
        )


@pytest.fixture
def server() -> MCPServer:
    tools = RepoStatusTools(StubRepoStatusSource())
    mcp = MCPServer("test")
    mcp.add_tool(tools.get_repo_status)
    return mcp


@pytest.mark.asyncio
async def test_get_repo_status_for_known_repo_returns_its_state(
    server: MCPServer,
) -> None:
    """Verify that a registered repo's index state reaches the caller."""
    async with Client(server) as client:
        result = await client.call_tool("get_repo_status", {"repo": KNOWN_REPO})

    assert result.structured_content["state"] == "ready"


@pytest.mark.asyncio
async def test_get_repo_status_for_known_repo_is_not_an_error(
    server: MCPServer,
) -> None:
    """Verify that a successful lookup is not flagged as a tool error."""
    async with Client(server) as client:
        result = await client.call_tool("get_repo_status", {"repo": KNOWN_REPO})

    assert result.is_error is False


@pytest.mark.asyncio
async def test_get_repo_status_for_unknown_repo_reports_a_tool_error(
    server: MCPServer,
) -> None:
    """Verify that an unregistered repo is flagged as an error, not as data.

    The calling LLM reads is_error to decide it must change course.
    """
    async with Client(server) as client:
        result = await client.call_tool("get_repo_status", {"repo": UNKNOWN_REPO})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_get_repo_status_error_for_unknown_repo_names_index_repo(
    server: MCPServer,
) -> None:
    """Verify that the error tells the LLM which tool to call next."""
    async with Client(server) as client:
        result = await client.call_tool("get_repo_status", {"repo": UNKNOWN_REPO})

    assert "index_repo" in result.content[0].text


@pytest.mark.asyncio
async def test_get_repo_status_is_described_for_the_calling_llm(
    server: MCPServer,
) -> None:
    """Verify that the tool ships a description, the model's only documentation."""
    async with Client(server) as client:
        result = await client.list_tools()

    assert result.tools[0].description


@pytest_asyncio.fixture
async def make_source() -> AsyncIterator[SourceFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(handler: Handler) -> HttpRepoStatusSource:
        client = httpx.AsyncClient(
            base_url=API_BASE_URL,
            transport=httpx.MockTransport(handler),
        )
        clients.append(client)
        return HttpRepoStatusSource(client)

    yield build

    for client in clients:
        await client.aclose()


def api_payload(
    status: str = "completed",
    file_statuses: tuple[str, ...] = ("indexed",),
    total_files_expected: int | None = 1,
) -> dict[str, Any]:
    return {
        "repo": {
            "status": status,
            "branch": "main",
            "commit_sha": "abc123",
            "total_files_expected": total_files_expected,
        },
        "files": [{"file_path": f"f{i}.py", "status": s} for i, s in enumerate(file_statuses)],
    }


def respond_with(payload: dict[str, Any]) -> Handler:
    return lambda request: httpx.Response(200, json=payload)


def respond_with_status(status_code: int) -> Handler:
    return lambda request: httpx.Response(status_code)


def fail_to_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest.mark.parametrize(
    "api_status,file_statuses,expected_state",
    [
        ("pending", (), RepoState.NOT_INDEXED),
        ("indexing", ("processing",), RepoState.INDEXING),
        ("paused", ("indexed",), RepoState.INDEXING),
        ("completed", ("indexed", "skipped"), RepoState.READY),
        ("failed", (), RepoState.FAILED),
        ("completed", ("indexed", "failed"), RepoState.FAILED),
    ],
)
@pytest.mark.asyncio
async def test_http_source_fetch_maps_api_status_to_repo_state(
    make_source: SourceFactory,
    api_status: str,
    file_statuses: tuple[str, ...],
    expected_state: RepoState,
) -> None:
    """Verify the api/ lifecycle status becomes the state the LLM reads.

    A completed index with failed files must never be reported as ready.
    """
    source = make_source(respond_with(api_payload(api_status, file_statuses)))

    status = await source.fetch(KNOWN_REPO)

    assert status.state == expected_state


@pytest.mark.asyncio
async def test_http_source_fetch_counts_indexed_files(make_source: SourceFactory) -> None:
    """Verify files_indexed counts only files whose status is indexed."""
    payload = api_payload(file_statuses=("indexed", "indexed", "failed", "skipped"))
    source = make_source(respond_with(payload))

    status = await source.fetch(KNOWN_REPO)

    assert status.files_indexed == 2


@pytest.mark.asyncio
async def test_http_source_fetch_counts_failed_files(make_source: SourceFactory) -> None:
    """Verify files_failed counts only files whose status is failed."""
    payload = api_payload(file_statuses=("indexed", "failed", "failed"))
    source = make_source(respond_with(payload))

    status = await source.fetch(KNOWN_REPO)

    assert status.files_failed == 2


@pytest.mark.asyncio
async def test_http_source_fetch_uses_expected_total_when_known(make_source: SourceFactory) -> None:
    """Verify files_total reports the planned total, not just the files seen so far."""
    payload = api_payload(file_statuses=("indexed",), total_files_expected=40)
    source = make_source(respond_with(payload))

    status = await source.fetch(KNOWN_REPO)

    assert status.files_total == 40


@pytest.mark.asyncio
async def test_http_source_fetch_falls_back_to_file_count_when_total_unknown(
    make_source: SourceFactory,
) -> None:
    """Verify files_total falls back to the listed files before indexing sets a total."""
    payload = api_payload(file_statuses=("pending", "pending"), total_files_expected=None)
    source = make_source(respond_with(payload))

    status = await source.fetch(KNOWN_REPO)

    assert status.files_total == 2


@pytest.mark.asyncio
async def test_http_source_fetch_reports_the_indexed_commit(make_source: SourceFactory) -> None:
    """Verify the commit stamped by api/ is returned as indexed_commit."""
    source = make_source(respond_with(api_payload()))

    status = await source.fetch(KNOWN_REPO)

    assert status.indexed_commit == "abc123"


@pytest.mark.asyncio
async def test_http_source_fetch_leaves_head_commit_unknown(make_source: SourceFactory) -> None:
    """Verify head_commit stays None while api/ cannot report the branch head."""
    source = make_source(respond_with(api_payload()))

    status = await source.fetch(KNOWN_REPO)

    assert status.head_commit is None


@pytest.mark.asyncio
async def test_http_source_fetch_asks_api_for_the_repo_with_its_files(
    make_source: SourceFactory,
) -> None:
    """Verify the request names the repo and asks for per-file state."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=api_payload())

    await make_source(record).fetch(KNOWN_REPO)

    assert dict(requests[0].url.params) == {"full_name": KNOWN_REPO, "with_files": "true"}


@pytest.mark.asyncio
async def test_http_source_fetch_for_unregistered_repo_raises_repo_not_found(
    make_source: SourceFactory,
) -> None:
    """Verify a 404 from api/ becomes RepoNotFound, which the tool turns into guidance."""
    source = make_source(respond_with_status(404))

    with pytest.raises(RepoNotFound):
        await source.fetch(UNKNOWN_REPO)


@pytest.mark.asyncio
async def test_http_source_fetch_on_server_error_raises_status_unavailable(
    make_source: SourceFactory,
) -> None:
    """Verify an api/ failure is not mistaken for an unregistered repo."""
    source = make_source(respond_with_status(500))

    with pytest.raises(RepoStatusUnavailable):
        await source.fetch(KNOWN_REPO)


@pytest.mark.asyncio
async def test_http_source_fetch_when_api_is_unreachable_raises_status_unavailable(
    make_source: SourceFactory,
) -> None:
    """Verify a network failure surfaces as RepoStatusUnavailable, not a raw httpx error."""
    source = make_source(fail_to_connect)

    with pytest.raises(RepoStatusUnavailable):
        await source.fetch(KNOWN_REPO)
