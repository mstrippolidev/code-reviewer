import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.server import mcp
from mcp_server.tools.repo_status import HttpRepoStatusSource
from mcp_server.tools.review import ReviewStatus, ReviewTools

REPO = "acme/api"
REPO_ID = 42
REVIEW_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
API_BASE_URL = "http://api.test"
PATHS = ["src/a.py", "src/b.py"]


def repo_payload(status: str = "completed", file_statuses: tuple[str, ...] = ("indexed", "indexed")) -> dict[str, Any]:
    return {
        "repo": {
            "repo_id": REPO_ID,
            "status": status,
            "branch": "main",
            "commit_sha": "abc123",
            "total_files_expected": len(file_statuses),
        },
        "files": [{"file_path": f"f{index}.py", "status": state} for index, state in enumerate(file_statuses)],
    }


def review_job_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "review_id": str(REVIEW_ID),
        "repo_id": REPO_ID,
        "status": "pending",
        "status_reason": None,
        "file_paths": PATHS,
        "agents": None,
        "result": None,
        "agent_entries": None,
    }
    return payload | overrides


class FakeApi:
    """Answers the two calls the tool makes, the repo lookup and the review submission, and records them."""

    def __init__(
        self,
        repo_response: httpx.Response | None = None,
        review_response: httpx.Response | None = None,
        review_unreachable: bool = False,
    ) -> None:
        self.repo_response = repo_response or httpx.Response(200, json=repo_payload())
        self.review_response = review_response or httpx.Response(202, json=review_job_payload())
        self.review_unreachable = review_unreachable
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET":
            return self.repo_response
        if self.review_unreachable:
            raise httpx.ConnectError("refused", request=request)
        return self.review_response

    def posted(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]


ToolFactory = Callable[[FakeApi], ReviewTools]


@pytest_asyncio.fixture
async def make_tool() -> AsyncIterator[ToolFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(api: FakeApi) -> ReviewTools:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(api))
        clients.append(client)
        return ReviewTools(client, HttpRepoStatusSource(client))

    yield build

    for client in clients:
        await client.aclose()


@pytest.mark.asyncio
async def test_review_repo_files_posts_to_the_review_path_of_the_resolved_repo(make_tool: ToolFactory) -> None:
    """Verify that the repo name is turned into the id api/ addresses the review route by."""
    api = FakeApi()

    await make_tool(api).review_repo_files(REPO, PATHS)

    assert api.posted()[0].url.path == f"/api/repos/{REPO_ID}/review"


@pytest.mark.asyncio
async def test_review_repo_files_sends_the_paths_and_the_requested_agents(make_tool: ToolFactory) -> None:
    """Verify that api/ receives exactly the files and agents the caller chose."""
    api = FakeApi()

    await make_tool(api).review_repo_files(REPO, PATHS, ["TEST", "TCASE"])

    assert json.loads(api.posted()[0].content) == {"file_paths": PATHS, "agents": ["TEST", "TCASE"]}


@pytest.mark.asyncio
async def test_review_repo_files_without_agents_sends_null_so_every_agent_runs(make_tool: ToolFactory) -> None:
    """Verify that an omitted agents list reaches api/ as null, which means no restriction."""
    api = FakeApi()

    await make_tool(api).review_repo_files(REPO, PATHS)

    assert json.loads(api.posted()[0].content)["agents"] is None


@pytest.mark.asyncio
async def test_review_repo_files_returns_the_review_id_to_poll(make_tool: ToolFactory) -> None:
    """Verify that the caller gets the id it needs for get_review."""
    started = await make_tool(FakeApi()).review_repo_files(REPO, PATHS)

    assert started.review_id == REVIEW_ID


@pytest.mark.asyncio
async def test_review_repo_files_returns_a_pending_status(make_tool: ToolFactory) -> None:
    """Verify that the review is reported as queued, not finished."""
    started = await make_tool(FakeApi()).review_repo_files(REPO, PATHS)

    assert started.status == ReviewStatus.PENDING


@pytest.mark.asyncio
async def test_review_repo_files_reports_how_many_files_were_accepted(make_tool: ToolFactory) -> None:
    """Verify that the file count comes from what api/ accepted."""
    started = await make_tool(FakeApi()).review_repo_files(REPO, PATHS)

    assert started.files_total == 2


@pytest.mark.asyncio
async def test_review_repo_files_echoes_the_agents_api_will_run(make_tool: ToolFactory) -> None:
    """Verify that the caller can see which agents the review was restricted to."""
    api = FakeApi(review_response=httpx.Response(202, json=review_job_payload(agents=["TEST"])))

    started = await make_tool(api).review_repo_files(REPO, PATHS, ["TEST"])

    assert started.agents == ["TEST"]


@pytest.mark.asyncio
async def test_review_repo_files_does_not_expose_the_numeric_repo_id(make_tool: ToolFactory) -> None:
    """Verify that the id used to address the repo stays between the server and api/."""
    started = await make_tool(FakeApi()).review_repo_files(REPO, PATHS)

    assert "repo_id" not in started.model_dump()


NOT_READY = [
    ("pending", (), "is not_indexed", "index_repo"),
    ("indexing", ("indexed", "processing"), "still being indexed", "get_repo_status"),
    ("failed", (), "Indexing of 'acme/api' failed,", "retry indexing"),
    ("completed", ("indexed", "failed", "failed"), "finished with 2 failed file", "retry indexing"),
]


@pytest.mark.parametrize("api_status,file_statuses,expected_text,next_step", NOT_READY)
@pytest.mark.asyncio
async def test_review_repo_files_refuses_a_repo_that_is_not_ready_and_names_the_next_step(
    make_tool: ToolFactory, api_status: str, file_statuses: tuple[str, ...], expected_text: str, next_step: str
) -> None:
    """Verify that each non-ready state explains itself and says what to do, instead of reviewing a partial index."""
    api = FakeApi(repo_response=httpx.Response(200, json=repo_payload(api_status, file_statuses)))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_repo_files(REPO, PATHS)

    assert expected_text in str(raised.value) and next_step in str(raised.value)


@pytest.mark.parametrize("api_status,file_statuses,expected_text,next_step", NOT_READY)
@pytest.mark.asyncio
async def test_review_repo_files_submits_nothing_for_a_repo_that_is_not_ready(
    make_tool: ToolFactory, api_status: str, file_statuses: tuple[str, ...], expected_text: str, next_step: str
) -> None:
    """Verify that no billed review job is created while the index is incomplete."""
    api = FakeApi(repo_response=httpx.Response(200, json=repo_payload(api_status, file_statuses)))

    with pytest.raises(ToolError):
        await make_tool(api).review_repo_files(REPO, PATHS)

    assert api.posted() == []


@pytest.mark.asyncio
async def test_review_repo_files_for_an_unregistered_repo_says_to_call_index_repo(make_tool: ToolFactory) -> None:
    """Verify that an unknown repo is reported with the tool that registers it."""
    api = FakeApi(repo_response=httpx.Response(404))

    with pytest.raises(ToolError, match="index_repo"):
        await make_tool(api).review_repo_files(REPO, PATHS)


@pytest.mark.asyncio
async def test_review_repo_files_when_the_repo_lookup_fails_tells_the_llm_to_retry(make_tool: ToolFactory) -> None:
    """Verify that an api/ failure while checking the repo is not mistaken for an unregistered repo."""
    api = FakeApi(repo_response=httpx.Response(500))

    with pytest.raises(ToolError, match="Try again shortly"):
        await make_tool(api).review_repo_files(REPO, PATHS)


def refusal(status_code: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=body, headers=headers)


REFUSALS = [
    (refusal(400, {"detail": "These files are not indexed for this repo: ['x.py']"}), "not indexed for this repo"),
    (refusal(400, {"detail": "These files are not indexed for this repo: ['x.py']"}), "call review_repo_files again"),
    (refusal(401, {"detail": "expired"}), "sign in again"),
    (refusal(404, {"detail": "gone"}), "can no longer access it"),
    (refusal(422, {"detail": [{"loc": ["body", "agents", 0], "msg": "Input should be 'SOLID1'"}]}), "agents: Input"),
    (refusal(422, {"detail": [{"loc": ["body", "agents", 0], "msg": "bad"}]}), "agents:// resource"),
    (refusal(429, {"detail": "Too many reviews"}), "Poll get_review"),
    (refusal(500, {"detail": "boom"}), "api/ answered 500"),
    (refusal(502, {"detail": "Could not queue this review"}), "Try again shortly"),
]


@pytest.mark.parametrize("review_response,expected_text", REFUSALS)
@pytest.mark.asyncio
async def test_review_repo_files_turns_an_api_refusal_into_a_tool_error_naming_the_next_step(
    make_tool: ToolFactory, review_response: httpx.Response, expected_text: str
) -> None:
    """Verify that each refusal from api/ tells the calling LLM what happened and what to do next."""
    api = FakeApi(review_response=review_response)

    with pytest.raises(ToolError, match=expected_text):
        await make_tool(api).review_repo_files(REPO, PATHS)


@pytest.mark.asyncio
async def test_review_repo_files_when_rate_limited_reports_how_long_to_wait(make_tool: ToolFactory) -> None:
    """Verify that the Retry-After from api/ reaches the LLM so it does not retry at once."""
    api = FakeApi(review_response=refusal(429, {"detail": "Too many reviews"}, {"Retry-After": "30"}))

    with pytest.raises(ToolError, match="Retry after 30 seconds"):
        await make_tool(api).review_repo_files(REPO, PATHS)


@pytest.mark.asyncio
async def test_review_repo_files_does_not_leak_an_unexpected_api_body(make_tool: ToolFactory) -> None:
    """Verify that internal details in a 500 body never reach the calling LLM."""
    api = FakeApi(review_response=refusal(500, {"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_repo_files(REPO, PATHS)

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_review_repo_files_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure while submitting surfaces as a ToolError, not a raw httpx error."""
    api = FakeApi(review_unreachable=True)

    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(api).review_repo_files(REPO, PATHS)


UNREADABLE_ACCEPTED_BODIES = [
    {"status": "pending"},
    ["not", "an", "object"],
    {"review_id": str(REVIEW_ID), "status": "pending", "agents": None},
    {"review_id": str(REVIEW_ID), "status": "pending", "file_paths": None, "agents": None},
    {"review_id": str(REVIEW_ID), "status": "archived", "file_paths": PATHS, "agents": None},
    {"review_id": "not-a-uuid", "status": "pending", "file_paths": PATHS, "agents": None},
    {"review_id": str(REVIEW_ID), "status": "pending", "file_paths": PATHS, "agents": "TEST"},
]
NON_JSON_ACCEPTED_BODIES = [b"<html>gateway</html>", b""]


@pytest.mark.parametrize("body", UNREADABLE_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_review_repo_files_when_the_accepted_answer_is_unreadable_warns_it_may_have_started(
    make_tool: ToolFactory, body: Any
) -> None:
    """Verify that an unreadable success answer tells the LLM not to resubmit at once and double the billed work."""
    api = FakeApi(review_response=httpx.Response(202, json=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).review_repo_files(REPO, PATHS)


@pytest.mark.parametrize("body", NON_JSON_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_review_repo_files_when_the_accepted_answer_is_not_json_warns_it_may_have_started(
    make_tool: ToolFactory, body: bytes
) -> None:
    """Verify that a 202 with a proxy error page or an empty body gets the same do-not-resubmit warning."""
    api = FakeApi(review_response=httpx.Response(202, content=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).review_repo_files(REPO, PATHS)


async def _listed_tool(name: str) -> Any:
    async with Client(mcp) as client:
        result = await client.list_tools()
    return next(tool for tool in result.tools if tool.name == name)


@pytest.mark.asyncio
async def test_server_lists_review_repo_files() -> None:
    """Verify that connecting clients are told the tool exists."""
    tool = await _listed_tool("review_repo_files")

    assert tool.name == "review_repo_files"


@pytest.mark.asyncio
async def test_review_repo_files_is_not_annotated_as_idempotent() -> None:
    """Verify that clients are told a repeated call starts another billed review."""
    tool = await _listed_tool("review_repo_files")

    assert tool.annotations.idempotent_hint is False


@pytest.mark.asyncio
async def test_review_repo_files_is_annotated_as_not_read_only() -> None:
    """Verify that clients are told the tool changes state by starting a review."""
    tool = await _listed_tool("review_repo_files")

    assert tool.annotations.read_only_hint is False


@pytest.mark.asyncio
async def test_review_repo_files_description_tells_the_llm_the_repo_must_be_indexed() -> None:
    """Verify that the model reads, before calling, that an unindexed repo has to go through index_repo first."""
    tool = await _listed_tool("review_repo_files")

    assert "index_repo" in tool.description
