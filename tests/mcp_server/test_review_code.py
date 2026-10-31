import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.server import mcp
from mcp_server.tools.repo_status import HttpRepoStatusSource
from mcp_server.tools.review import REVIEW_PATH, FileData, ReviewStatus, ReviewTools
from tests.mcp_server.test_review_repo_files import (
    NON_JSON_ACCEPTED_BODIES,
    REVIEW_ID,
    UNREADABLE_ACCEPTED_BODIES,
    FakeApi,
    refusal,
    review_job_payload,
)

FILES = [
    FileData(file_path="src/service.py", content="def run():\n    return 1\n"),
    FileData(file_path="tests/test_service.py", content="def test_run():\n    assert run() == 1\n"),
]
API_BASE_URL = "http://api.test"

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
async def test_review_code_posts_to_the_repoless_review_path(make_tool: ToolFactory) -> None:
    """Verify that the files go to the endpoint for logged-in users, not to a repo route."""
    api = FakeApi()

    await make_tool(api).review_code(FILES)

    assert (api.posted()[0].method, api.posted()[0].url.path) == ("POST", REVIEW_PATH)


@pytest.mark.asyncio
async def test_review_code_looks_up_no_repo(make_tool: ToolFactory) -> None:
    """Verify that a review with no repo makes no repo lookup and needs no indexed repo."""
    api = FakeApi()

    await make_tool(api).review_code(FILES)

    assert [request.method for request in api.requests] == ["POST"]


@pytest.mark.asyncio
async def test_review_code_sends_each_files_path_and_content(make_tool: ToolFactory) -> None:
    """Verify that api/ receives the source itself, since it has no repo to read it from."""
    api = FakeApi()

    await make_tool(api).review_code(FILES)

    sent = json.loads(api.posted()[0].content)["files"]
    assert sent == [
        {"file_path": "src/service.py", "content": "def run():\n    return 1\n"},
        {"file_path": "tests/test_service.py", "content": "def test_run():\n    assert run() == 1\n"},
    ]


@pytest.mark.asyncio
async def test_review_code_sends_the_requested_agents(make_tool: ToolFactory) -> None:
    """Verify that the agent subset the caller chose reaches api/."""
    api = FakeApi()

    await make_tool(api).review_code(FILES, ["TEST", "TCASE"])

    assert json.loads(api.posted()[0].content)["agents"] == ["TEST", "TCASE"]


@pytest.mark.asyncio
async def test_review_code_without_agents_sends_null_so_every_agent_runs(make_tool: ToolFactory) -> None:
    """Verify that an omitted agents list reaches api/ as null, which means no restriction."""
    api = FakeApi()

    await make_tool(api).review_code(FILES)

    assert json.loads(api.posted()[0].content)["agents"] is None


@pytest.mark.asyncio
async def test_review_code_returns_the_review_id_to_poll(make_tool: ToolFactory) -> None:
    """Verify that the caller gets the id it needs for get_review."""
    started = await make_tool(FakeApi()).review_code(FILES)

    assert started.review_id == REVIEW_ID


@pytest.mark.asyncio
async def test_review_code_returns_a_pending_status(make_tool: ToolFactory) -> None:
    """Verify that the review is reported as queued, not finished."""
    started = await make_tool(FakeApi()).review_code(FILES)

    assert started.status == ReviewStatus.PENDING


@pytest.mark.asyncio
async def test_review_code_echoes_the_agents_api_will_run(make_tool: ToolFactory) -> None:
    """Verify that the caller can see which agents the review was restricted to."""
    api = FakeApi(review_response=httpx.Response(202, json=review_job_payload(agents=["TEST"])))

    started = await make_tool(api).review_code(FILES, ["TEST"])

    assert started.agents == ["TEST"]


REPOLESS_REFUSALS = [
    (refusal(401, {"detail": "expired"}), "call review_code again"),
    (
        refusal(422, {"detail": [{"loc": ["body", "agents"], "msg": "Value error, DRY cannot run with no repo"}]}),
        "agents: DRY cannot run with no repo",
    ),
    (refusal(422, {"detail": [{"loc": ["body", "files"], "msg": "bad"}]}), "agents:// resource"),
    (refusal(429, {"detail": "Too many reviews"}), "Poll get_review"),
    (refusal(404, {"detail": "gone"}), "api/ answered 404"),
    (refusal(500, {"detail": "boom"}), "api/ answered 500"),
    (refusal(502, {"detail": "Could not queue this review"}), "Try again shortly"),
]


@pytest.mark.parametrize("review_response,expected_text", REPOLESS_REFUSALS)
@pytest.mark.asyncio
async def test_review_code_turns_an_api_refusal_into_a_tool_error_naming_the_next_step(
    make_tool: ToolFactory, review_response: httpx.Response, expected_text: str
) -> None:
    """Verify that each refusal from api/ tells the calling LLM what happened and what to do next."""
    api = FakeApi(review_response=review_response)

    with pytest.raises(ToolError, match=expected_text):
        await make_tool(api).review_code(FILES)


@pytest.mark.asyncio
async def test_review_code_never_talks_about_a_repo_in_its_refusals(make_tool: ToolFactory) -> None:
    """Verify that a 404 on a review with no repo is not explained as a missing repo."""
    api = FakeApi(review_response=refusal(404, {"detail": "gone"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_code(FILES)

    assert "Repo" not in str(raised.value)


@pytest.mark.asyncio
async def test_review_code_when_rate_limited_reports_how_long_to_wait(make_tool: ToolFactory) -> None:
    """Verify that the Retry-After from api/ reaches the LLM so it does not retry at once."""
    api = FakeApi(review_response=refusal(429, {"detail": "Too many reviews"}, {"Retry-After": "30"}))

    with pytest.raises(ToolError, match="Retry after 30 seconds"):
        await make_tool(api).review_code(FILES)


@pytest.mark.asyncio
async def test_review_code_does_not_leak_an_unexpected_api_body(make_tool: ToolFactory) -> None:
    """Verify that internal details in a 500 body never reach the calling LLM."""
    api = FakeApi(review_response=refusal(500, {"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_code(FILES)

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_review_code_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure while submitting surfaces as a ToolError, not a raw httpx error."""
    api = FakeApi(review_unreachable=True)

    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(api).review_code(FILES)


@pytest.mark.parametrize("body", UNREADABLE_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_review_code_when_the_accepted_answer_is_unreadable_warns_it_may_have_started(
    make_tool: ToolFactory, body: Any
) -> None:
    """Verify that an unreadable success answer tells the LLM not to resubmit at once and double the billed work."""
    api = FakeApi(review_response=httpx.Response(202, json=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).review_code(FILES)


@pytest.mark.parametrize("body", NON_JSON_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_review_code_when_the_accepted_answer_is_not_json_warns_it_may_have_started(
    make_tool: ToolFactory, body: bytes
) -> None:
    """Verify that a 202 with a proxy error page or an empty body gets the same do-not-resubmit warning."""
    api = FakeApi(review_response=httpx.Response(202, content=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).review_code(FILES)


async def _listed_tool(name: str) -> Any:
    async with Client(mcp) as client:
        result = await client.list_tools()
    return next(tool for tool in result.tools if tool.name == name)


@pytest.mark.asyncio
async def test_server_lists_review_code() -> None:
    """Verify that connecting clients are told the tool exists."""
    tool = await _listed_tool("review_code")

    assert tool.name == "review_code"


@pytest.mark.asyncio
async def test_review_code_is_not_annotated_as_idempotent() -> None:
    """Verify that clients are told a repeated call starts another billed review."""
    tool = await _listed_tool("review_code")

    assert tool.annotations.idempotent_hint is False


@pytest.mark.asyncio
async def test_review_code_is_annotated_as_not_read_only() -> None:
    """Verify that clients are told the tool changes state by starting a review."""
    tool = await _listed_tool("review_code")

    assert tool.annotations.read_only_hint is False


@pytest.mark.asyncio
async def test_review_code_input_schema_asks_for_a_path_and_content_per_file() -> None:
    """Verify that the model is told each file needs both its path and its source."""
    tool = await _listed_tool("review_code")

    file_schema = tool.input_schema["$defs"]["FileData"]
    assert sorted(file_schema["required"]) == ["content", "file_path"]


@pytest.mark.parametrize(
    "expected_text",
    ["DRY does not run", "ARCH and COUP", "TCASE sees only the test files", "Only Python", "get_review", "untrusted"],
)
@pytest.mark.asyncio
async def test_review_code_description_states_what_the_model_must_know_before_calling(expected_text: str) -> None:
    """Verify that the limits of a review with no repo are written where the LLM reads them."""
    tool = await _listed_tool("review_code")

    assert expected_text in tool.description
