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
from mcp_server.tools.review import FileData, ReviewStatus, ReviewTools

PR_URL = "https://github.com/acme/api/pull/7"
REVIEW_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
API_BASE_URL = "http://api.test"
WAITING_REASON = "Waiting for the repo to finish indexing"


def review_job_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "review_id": str(REVIEW_ID),
        "repo_id": 42,
        "status": "pending",
        "status_reason": None,
        "file_paths": [],
        "pr_number": 7,
        "head_sha": "head-sha",
        "agents": None,
        "result": None,
        "agent_entries": None,
    }
    return payload | overrides


class FakeApi:
    """Answers the one call the tool makes, the pull request submission, and records every request it receives."""

    def __init__(self, response: httpx.Response | None = None, unreachable: bool = False) -> None:
        self.response = response or httpx.Response(202, json=review_job_payload())
        self.unreachable = unreachable
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.unreachable:
            raise httpx.ConnectError("refused", request=request)
        return self.response


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


def refusal(status_code: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=body, headers=headers)


@pytest.mark.asyncio
async def test_review_pr_posts_to_the_pull_request_review_path(make_tool: ToolFactory) -> None:
    """Verify the URL goes to the endpoint that reads the pull request and queues the review."""
    api = FakeApi()

    await make_tool(api).review_pr(PR_URL)

    assert api.requests[0].url.path == "/api/pull-requests/review"


@pytest.mark.asyncio
async def test_review_pr_makes_no_repo_lookup_of_its_own(make_tool: ToolFactory) -> None:
    """Verify readiness is left to api/, so a repo that is not indexed yet is not refused here."""
    api = FakeApi()

    await make_tool(api).review_pr(PR_URL)

    assert [request.method for request in api.requests] == ["POST"]


@pytest.mark.asyncio
async def test_review_pr_sends_the_url_and_the_requested_agents(make_tool: ToolFactory) -> None:
    """Verify api/ receives exactly the pull request and agents the caller chose."""
    api = FakeApi()

    await make_tool(api).review_pr(PR_URL, ["TEST", "DRY"])

    assert json.loads(api.requests[0].content) == {"pr_url": PR_URL, "agents": ["TEST", "DRY"]}


@pytest.mark.asyncio
async def test_review_pr_without_agents_sends_null_so_every_agent_runs(make_tool: ToolFactory) -> None:
    """Verify an omitted agents list reaches api/ as null, which means no restriction."""
    api = FakeApi()

    await make_tool(api).review_pr(PR_URL)

    assert json.loads(api.requests[0].content)["agents"] is None


@pytest.mark.asyncio
async def test_review_pr_returns_the_review_id_to_poll(make_tool: ToolFactory) -> None:
    """Verify the caller gets the id it needs for get_review."""
    started = await make_tool(FakeApi()).review_pr(PR_URL)

    assert started.review_id == REVIEW_ID


@pytest.mark.asyncio
async def test_review_pr_returns_a_pending_status(make_tool: ToolFactory) -> None:
    """Verify the review is reported as queued, not finished."""
    started = await make_tool(FakeApi()).review_pr(PR_URL)

    assert started.status == ReviewStatus.PENDING


@pytest.mark.asyncio
async def test_review_pr_reports_that_a_review_is_waiting_for_the_repo_to_index(make_tool: ToolFactory) -> None:
    """Verify the model can tell indexing was started and the review will take longer, instead of guessing."""
    api = FakeApi(httpx.Response(202, json=review_job_payload(status_reason=WAITING_REASON)))

    started = await make_tool(api).review_pr(PR_URL)

    assert started.status_reason == WAITING_REASON


@pytest.mark.asyncio
async def test_review_pr_for_an_indexed_repo_has_no_status_reason(make_tool: ToolFactory) -> None:
    """Verify a review queued at once does not claim to be waiting."""
    started = await make_tool(FakeApi()).review_pr(PR_URL)

    assert started.status_reason is None


@pytest.mark.asyncio
async def test_review_pr_reports_zero_files_until_the_worker_has_read_the_pull_request(
    make_tool: ToolFactory,
) -> None:
    """Verify the file count is the real one api/ reports (none known yet), not an invented number."""
    started = await make_tool(FakeApi()).review_pr(PR_URL)

    assert started.files_total == 0


@pytest.mark.asyncio
async def test_review_pr_echoes_the_agents_api_will_run(make_tool: ToolFactory) -> None:
    """Verify the caller can see which agents the review was restricted to."""
    api = FakeApi(httpx.Response(202, json=review_job_payload(agents=["TEST"])))

    started = await make_tool(api).review_pr(PR_URL, ["TEST"])

    assert started.agents == ["TEST"]


@pytest.mark.asyncio
async def test_review_code_still_reports_no_status_reason(make_tool: ToolFactory) -> None:
    """Verify adding status_reason to the shared result did not change the repoless tool's answer."""
    started = await make_tool(FakeApi()).review_code([FileData(file_path="a.py", content="x = 1\n")])

    assert started.status_reason is None


REFUSALS = [
    (refusal(400, {"detail": "This repo has too little Python"}), "too little Python"),
    (refusal(400, {"detail": "This repo has too little Python"}), "cannot be reviewed"),
    (refusal(401, {"detail": "expired"}), "sign in again"),
    (refusal(401, {"detail": "expired"}), "call review_pr again"),
    (refusal(404, {"detail": "Pull request 7 was not found in acme/api, or you cannot see it"}), "was not found"),
    (refusal(404, {"detail": "Pull request 7 was not found in acme/api, or you cannot see it"}), "Check the pull request URL"),
    (refusal(409, {"detail": "This repo's indexing is failed. Ask the person who registered it to retry"}), "Ask the person who registered it"),
    (refusal(422, {"detail": [{"loc": ["body", "pr_url"], "msg": "Value error, Not a pull request URL"}]}), "pr_url: Not a pull request URL"),
    (refusal(422, {"detail": [{"loc": ["body", "pr_url"], "msg": "bad"}]}), "https://github.com/owner/repo/pull/123"),
    (refusal(422, {"detail": [{"loc": ["body", "agents"], "msg": "bad"}]}), "agents:// resource"),
    (refusal(422, {"detail": "Pull request 7 is not open, so it is not reviewed"}), "is not open"),
    (refusal(422, {"detail": "Pull request 7 is not open, so it is not reviewed"}), "will not help"),
    (refusal(429, {"detail": "You already have 3 reviews running or waiting"}), "Poll get_review"),
    (refusal(500, {"detail": "boom"}), "api/ answered 500"),
    (refusal(502, {"detail": "Could not queue this review"}), "The review was not started"),
    (refusal(502, {"detail": "Could not queue this review"}), "call review_pr again after a short wait"),
]


@pytest.mark.parametrize("response,expected_text", REFUSALS)
@pytest.mark.asyncio
async def test_review_pr_turns_an_api_refusal_into_a_tool_error_naming_the_next_step(
    make_tool: ToolFactory, response: httpx.Response, expected_text: str
) -> None:
    """Verify each refusal from api/ tells the calling LLM what happened and what to do next."""
    with pytest.raises(ToolError, match=expected_text):
        await make_tool(FakeApi(response)).review_pr(PR_URL)


@pytest.mark.asyncio
async def test_review_pr_does_not_suggest_retrying_a_pull_request_that_can_never_be_reviewed(
    make_tool: ToolFactory,
) -> None:
    """Verify a final refusal does not send the model into a loop of identical calls."""
    api = FakeApi(refusal(422, {"detail": "This pull request changes 150 files; at most 100 can be reviewed"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_pr(PR_URL)

    assert "call review_pr again." not in str(raised.value)


@pytest.mark.asyncio
async def test_review_pr_when_rate_limited_reports_how_long_to_wait(make_tool: ToolFactory) -> None:
    """Verify the Retry-After from api/ reaches the LLM so it does not retry at once."""
    api = FakeApi(refusal(429, {"detail": "Too many reviews"}, {"Retry-After": "30"}))

    with pytest.raises(ToolError, match="Retry after 30 seconds"):
        await make_tool(api).review_pr(PR_URL)


@pytest.mark.asyncio
async def test_review_pr_at_the_unfinished_review_cap_has_no_wait_time_to_report(make_tool: ToolFactory) -> None:
    """Verify the cap, which sends no Retry-After, is still explained and points at polling."""
    api = FakeApi(refusal(429, {"detail": "You already have 3 reviews running or waiting. Wait for one to finish"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_pr(PR_URL)

    assert "Retry after" not in str(raised.value) and "Poll get_review" in str(raised.value)


@pytest.mark.asyncio
async def test_review_pr_does_not_leak_an_unexpected_api_body(make_tool: ToolFactory) -> None:
    """Verify internal details in a 500 body never reach the calling LLM."""
    api = FakeApi(refusal(500, {"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).review_pr(PR_URL)

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_review_pr_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify a network failure while submitting surfaces as a ToolError, not a raw httpx error."""
    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(FakeApi(unreachable=True)).review_pr(PR_URL)


UNREADABLE_ACCEPTED_BODIES = [
    {"status": "pending"},
    ["not", "an", "object"],
    {"review_id": str(REVIEW_ID), "status": "pending", "agents": None},
    {"review_id": str(REVIEW_ID), "status": "archived", "file_paths": [], "agents": None},
    {"review_id": "not-a-uuid", "status": "pending", "file_paths": [], "agents": None},
]


@pytest.mark.parametrize("body", UNREADABLE_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_review_pr_when_the_accepted_answer_is_unreadable_warns_it_may_have_started(
    make_tool: ToolFactory, body: Any
) -> None:
    """Verify an unreadable success answer tells the LLM not to resubmit at once, which could double the spend."""
    with pytest.raises(ToolError, match="may have started"):
        await make_tool(FakeApi(httpx.Response(202, json=body))).review_pr(PR_URL)


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b""])
@pytest.mark.asyncio
async def test_review_pr_when_the_accepted_answer_is_not_json_warns_it_may_have_started(
    make_tool: ToolFactory, body: bytes
) -> None:
    """Verify a 202 with a proxy error page or an empty body gets the same do-not-resubmit warning."""
    with pytest.raises(ToolError, match="may have started"):
        await make_tool(FakeApi(httpx.Response(202, content=body))).review_pr(PR_URL)


async def _listed_tool(name: str) -> Any:
    async with Client(mcp) as client:
        result = await client.list_tools()
    return next(tool for tool in result.tools if tool.name == name)


@pytest.mark.asyncio
async def test_server_lists_review_pr() -> None:
    """Verify connecting clients are told the tool exists."""
    tool = await _listed_tool("review_pr")

    assert tool.name == "review_pr"


@pytest.mark.asyncio
async def test_review_pr_takes_the_url_as_its_only_required_argument() -> None:
    """Verify the model is not asked for a repo or a number that the URL already names."""
    tool = await _listed_tool("review_pr")

    assert tool.input_schema["required"] == ["pr_url"]


@pytest.mark.asyncio
async def test_review_pr_is_not_annotated_as_idempotent() -> None:
    """Verify clients are told a repeated call starts another billed review."""
    tool = await _listed_tool("review_pr")

    assert tool.annotations.idempotent_hint is False


@pytest.mark.asyncio
async def test_review_pr_is_annotated_as_not_read_only() -> None:
    """Verify clients are told the tool changes state by starting a review, and possibly indexing."""
    tool = await _listed_tool("review_pr")

    assert tool.annotations.read_only_hint is False


@pytest.mark.parametrize(
    "phrase", ["get_review", "indexing", "100 changed files", "untrusted", "agents://", "never indexed"]
)
@pytest.mark.asyncio
async def test_review_pr_description_tells_the_llm_what_it_needs_to_know(phrase: str) -> None:
    """Verify the model reads, before calling, how to get the answer, what it may cost, and its limits."""
    tool = await _listed_tool("review_pr")

    assert phrase in tool.description
