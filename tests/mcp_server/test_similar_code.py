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
from mcp_server.tools.similar_code import SimilarCodeStatus, SimilarCodeTools

REPO = "acme/api"
REPO_ID = 42
SEARCH_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
API_BASE_URL = "http://api.test"
SNIPPET = "def add(a, b):\n    return a + b\n"
INCIDENT = {
    "priority": "high",
    "line_position": "1-2",
    "description": "add is structurally identical to legacy/ops.py:add (lines 4-5).",
    "advice": "Extract the shared logic.",
}


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


def search_payload(**overrides: Any) -> dict[str, Any]:
    payload = {"search_id": str(SEARCH_ID), "status": "pending", "status_reason": None, "incidents": None}
    return payload | overrides


class FakeApi:
    """Answers the three calls the tools make, the repo lookup, the submission and the poll, and records them."""

    def __init__(
        self,
        repo_response: httpx.Response | None = None,
        submit_response: httpx.Response | None = None,
        search_response: httpx.Response | None = None,
        submit_unreachable: bool = False,
        search_unreachable: bool = False,
    ) -> None:
        self.repo_response = repo_response or httpx.Response(200, json=repo_payload())
        self.submit_response = submit_response or httpx.Response(202, json=search_payload())
        self.search_response = search_response or httpx.Response(200, json=search_payload())
        self.submit_unreachable = submit_unreachable
        self.search_unreachable = search_unreachable
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/repos/name":
            return self.repo_response
        if request.method == "POST":
            if self.submit_unreachable:
                raise httpx.ConnectError("refused", request=request)
            return self.submit_response
        if self.search_unreachable:
            raise httpx.ConnectError("refused", request=request)
        return self.search_response

    def posted(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.method == "POST"]

    def polled(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path.startswith("/api/similar-code/")]


ToolFactory = Callable[[FakeApi], SimilarCodeTools]


@pytest_asyncio.fixture
async def make_tool() -> AsyncIterator[ToolFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(api: FakeApi) -> SimilarCodeTools:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(api))
        clients.append(client)
        return SimilarCodeTools(client, HttpRepoStatusSource(client))

    yield build

    for client in clients:
        await client.aclose()


def refusal(status_code: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=body, headers=headers)


def polled_with(payload: dict[str, Any]) -> FakeApi:
    return FakeApi(search_response=httpx.Response(200, json=payload))


@pytest.mark.asyncio
async def test_find_similar_code_posts_to_the_similar_code_path_of_the_resolved_repo(make_tool: ToolFactory) -> None:
    """Verify that the repo name is turned into the id api/ addresses the search route by."""
    api = FakeApi()

    await make_tool(api).find_similar_code(REPO, SNIPPET)

    assert api.posted()[0].url.path == f"/api/repos/{REPO_ID}/similar-code"


@pytest.mark.asyncio
async def test_find_similar_code_sends_the_snippet_unchanged(make_tool: ToolFactory) -> None:
    """Verify that api/ receives exactly the code the caller passed."""
    api = FakeApi()

    await make_tool(api).find_similar_code(REPO, SNIPPET)

    assert json.loads(api.posted()[0].content) == {"code": SNIPPET}


@pytest.mark.asyncio
async def test_find_similar_code_returns_the_search_id_to_poll(make_tool: ToolFactory) -> None:
    """Verify that the caller gets the id it needs for get_similar_code_result."""
    started = await make_tool(FakeApi()).find_similar_code(REPO, SNIPPET)

    assert started.search_id == SEARCH_ID


@pytest.mark.asyncio
async def test_find_similar_code_returns_a_pending_status(make_tool: ToolFactory) -> None:
    """Verify that the search is reported as queued, not finished."""
    started = await make_tool(FakeApi()).find_similar_code(REPO, SNIPPET)

    assert started.status == SimilarCodeStatus.PENDING


@pytest.mark.asyncio
async def test_find_similar_code_does_not_expose_the_numeric_repo_id(make_tool: ToolFactory) -> None:
    """Verify that the id used to address the repo stays between the server and api/."""
    started = await make_tool(FakeApi()).find_similar_code(REPO, SNIPPET)

    assert "repo_id" not in started.model_dump()


NOT_READY = [
    ("pending", (), "is not_indexed", "index_repo"),
    ("indexing", ("indexed", "processing"), "still being indexed", "get_repo_status"),
    ("failed", (), "Indexing of 'acme/api' failed,", "retry indexing"),
    ("completed", ("indexed", "failed", "failed"), "finished with 2 failed file", "retry indexing"),
]


@pytest.mark.parametrize("api_status,file_statuses,expected_text,next_step", NOT_READY)
@pytest.mark.asyncio
async def test_find_similar_code_refuses_a_repo_that_is_not_ready_and_names_the_next_step(
    make_tool: ToolFactory, api_status: str, file_statuses: tuple[str, ...], expected_text: str, next_step: str
) -> None:
    """Verify that each non-ready state explains itself and says what to do, instead of searching a partial index."""
    api = FakeApi(repo_response=httpx.Response(200, json=repo_payload(api_status, file_statuses)))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).find_similar_code(REPO, SNIPPET)

    assert expected_text in str(raised.value) and next_step in str(raised.value)


@pytest.mark.parametrize("api_status,file_statuses,expected_text,next_step", NOT_READY)
@pytest.mark.asyncio
async def test_find_similar_code_submits_nothing_for_a_repo_that_is_not_ready(
    make_tool: ToolFactory, api_status: str, file_statuses: tuple[str, ...], expected_text: str, next_step: str
) -> None:
    """Verify that no billed search is created while the index is incomplete."""
    api = FakeApi(repo_response=httpx.Response(200, json=repo_payload(api_status, file_statuses)))

    with pytest.raises(ToolError):
        await make_tool(api).find_similar_code(REPO, SNIPPET)

    assert api.posted() == []


@pytest.mark.asyncio
async def test_find_similar_code_for_an_indexing_repo_says_to_call_find_similar_code_again(
    make_tool: ToolFactory,
) -> None:
    """Verify that the shared readiness message names this tool, not the review tool it was written for."""
    api = FakeApi(repo_response=httpx.Response(200, json=repo_payload("indexing", ("indexed", "processing"))))

    with pytest.raises(ToolError, match="call find_similar_code again"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.asyncio
async def test_find_similar_code_for_an_unregistered_repo_says_to_call_index_repo(make_tool: ToolFactory) -> None:
    """Verify that an unknown repo is reported with the tool that registers it."""
    api = FakeApi(repo_response=httpx.Response(404))

    with pytest.raises(ToolError, match="index_repo"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.asyncio
async def test_find_similar_code_when_the_repo_lookup_fails_tells_the_llm_to_retry(make_tool: ToolFactory) -> None:
    """Verify that an api/ failure while checking the repo is not mistaken for an unregistered repo."""
    api = FakeApi(repo_response=httpx.Response(500))

    with pytest.raises(ToolError, match="Try again shortly"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


REFUSALS = [
    (refusal(401, {"detail": "expired"}), "sign in again"),
    (refusal(404, {"detail": "gone"}), "can no longer access it"),
    (refusal(409, {"detail": "Repo is not fully indexed yet"}), "no longer fully indexed"),
    (refusal(409, {"detail": "Repo is not fully indexed yet"}), "Call get_repo_status"),
    (refusal(422, {"detail": [{"loc": ["body", "code"], "msg": "String should have at least 1 character"}]}), "code: String should"),
    (refusal(422, {"detail": [{"loc": ["body", "code"], "msg": "bad"}]}), "call find_similar_code again"),
    (refusal(429, {"detail": "Too many searches"}), "Poll get_similar_code_result"),
    (refusal(500, {"detail": "boom"}), "api/ answered 500"),
    (refusal(502, {"detail": "Could not queue this search"}), "try again shortly"),
]


@pytest.mark.parametrize("submit_response,expected_text", REFUSALS)
@pytest.mark.asyncio
async def test_find_similar_code_turns_an_api_refusal_into_a_tool_error_naming_the_next_step(
    make_tool: ToolFactory, submit_response: httpx.Response, expected_text: str
) -> None:
    """Verify that each refusal from api/ tells the calling LLM what happened and what to do next."""
    api = FakeApi(submit_response=submit_response)

    with pytest.raises(ToolError, match=expected_text):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.asyncio
async def test_find_similar_code_when_rate_limited_reports_how_long_to_wait(make_tool: ToolFactory) -> None:
    """Verify that the Retry-After from api/ reaches the LLM so it does not retry at once."""
    api = FakeApi(submit_response=refusal(429, {"detail": "Too many searches"}, {"Retry-After": "30"}))

    with pytest.raises(ToolError, match="Retry after 30 seconds"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.asyncio
async def test_find_similar_code_does_not_leak_an_unexpected_api_body(make_tool: ToolFactory) -> None:
    """Verify that internal details in a 500 body never reach the calling LLM."""
    api = FakeApi(submit_response=refusal(500, {"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).find_similar_code(REPO, SNIPPET)

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_find_similar_code_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure while submitting surfaces as a ToolError, not a raw httpx error."""
    api = FakeApi(submit_unreachable=True)

    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


UNREADABLE_ACCEPTED_BODIES = [
    {"status": "pending"},
    ["not", "an", "object"],
    {"search_id": str(SEARCH_ID)},
    {"search_id": str(SEARCH_ID), "status": "archived"},
    {"search_id": "not-a-uuid", "status": "pending"},
]


@pytest.mark.parametrize("body", UNREADABLE_ACCEPTED_BODIES)
@pytest.mark.asyncio
async def test_find_similar_code_when_the_accepted_answer_is_unreadable_warns_it_may_have_started(
    make_tool: ToolFactory, body: Any
) -> None:
    """Verify that an unreadable success answer tells the LLM not to resubmit at once and double the billed work."""
    api = FakeApi(submit_response=httpx.Response(202, json=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b""])
@pytest.mark.asyncio
async def test_find_similar_code_when_the_accepted_answer_is_not_json_warns_it_may_have_started(
    make_tool: ToolFactory, body: bytes
) -> None:
    """Verify that a 202 with a proxy error page or an empty body gets the same do-not-resubmit warning."""
    api = FakeApi(submit_response=httpx.Response(202, content=body))

    with pytest.raises(ToolError, match="may have started"):
        await make_tool(api).find_similar_code(REPO, SNIPPET)


@pytest.mark.asyncio
async def test_get_similar_code_result_reads_the_search_route_for_the_id(make_tool: ToolFactory) -> None:
    """Verify that the poll asks api/ about exactly the search the caller named."""
    api = FakeApi()

    await make_tool(api).get_similar_code_result(SEARCH_ID)

    assert api.polled()[0].url.path == f"/api/similar-code/{SEARCH_ID}"


@pytest.mark.parametrize("status", ["pending", "running"])
@pytest.mark.asyncio
async def test_get_similar_code_result_while_unfinished_tells_the_llm_to_poll_again(
    make_tool: ToolFactory, status: str
) -> None:
    """Verify that an unfinished search is reported with the next call, not as an answer."""
    result = await make_tool(polled_with(search_payload(status=status))).get_similar_code_result(SEARCH_ID)

    assert "call get_similar_code_result again" in result.next_step


@pytest.mark.asyncio
async def test_get_similar_code_result_while_unfinished_has_no_findings_yet(make_tool: ToolFactory) -> None:
    """Verify that an unfinished search cannot be mistaken for one that found nothing."""
    result = await make_tool(polled_with(search_payload(status="running"))).get_similar_code_result(SEARCH_ID)

    assert (result.findings, result.similar_code_found) == (None, None)


@pytest.mark.asyncio
async def test_get_similar_code_result_completed_with_a_duplicate_reports_the_findings(
    make_tool: ToolFactory,
) -> None:
    """Verify that the existing location api/ found reaches the LLM."""
    payload = search_payload(status="completed", incidents=[INCIDENT])

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert result.findings[0].description == INCIDENT["description"]


@pytest.mark.asyncio
async def test_get_similar_code_result_completed_with_a_duplicate_says_similar_code_was_found(
    make_tool: ToolFactory,
) -> None:
    """Verify that the yes/no answer is explicit, not left for the LLM to infer from a list."""
    payload = search_payload(status="completed", incidents=[INCIDENT])

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert result.similar_code_found is True


@pytest.mark.asyncio
async def test_get_similar_code_result_completed_with_nothing_found_says_so(make_tool: ToolFactory) -> None:
    """Verify that an empty answer is a definite no, distinct from an unfinished search."""
    payload = search_payload(status="completed", incidents=[])

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert (result.similar_code_found, result.findings) == (False, [])


@pytest.mark.asyncio
async def test_get_similar_code_result_completed_has_no_next_step(make_tool: ToolFactory) -> None:
    """Verify that a finished search does not tell the LLM to keep polling."""
    payload = search_payload(status="completed", incidents=[])

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert result.next_step is None


@pytest.mark.asyncio
async def test_get_similar_code_result_rejected_carries_the_reason(make_tool: ToolFactory) -> None:
    """Verify that the caller learns why the snippet was refused."""
    payload = search_payload(status="rejected", status_reason="The snippet could not be split")

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert result.status_reason == "The snippet could not be split"


@pytest.mark.asyncio
async def test_get_similar_code_result_rejected_tells_the_llm_to_fix_the_snippet(make_tool: ToolFactory) -> None:
    """Verify that a refused snippet is not retried unchanged."""
    payload = search_payload(status="rejected", status_reason="not source code")

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert "Fix the snippet" in result.next_step


@pytest.mark.asyncio
async def test_get_similar_code_result_failed_tells_the_llm_it_can_search_again(make_tool: ToolFactory) -> None:
    """Verify that a service failure is reported as retryable, unlike a refused snippet."""
    payload = search_payload(status="failed", status_reason="Could not check this snippet against the repo")

    result = await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)

    assert "Call find_similar_code again" in result.next_step


@pytest.mark.asyncio
async def test_get_similar_code_result_for_an_unknown_search_says_it_was_not_found(make_tool: ToolFactory) -> None:
    """Verify that an id the account does not own is reported with where the id should have come from."""
    api = FakeApi(search_response=httpx.Response(404))

    with pytest.raises(ToolError, match="was not found for this account"):
        await make_tool(api).get_similar_code_result(SEARCH_ID)


@pytest.mark.asyncio
async def test_get_similar_code_result_when_api_fails_tells_the_llm_to_retry(make_tool: ToolFactory) -> None:
    """Verify that an api/ failure is not reported as a missing search."""
    api = FakeApi(search_response=httpx.Response(500, json={"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await make_tool(api).get_similar_code_result(SEARCH_ID)

    assert "Try again shortly" in str(raised.value) and "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_get_similar_code_result_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure while polling surfaces as a ToolError, not a raw httpx error."""
    api = FakeApi(search_unreachable=True)

    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(api).get_similar_code_result(SEARCH_ID)


@pytest.mark.asyncio
async def test_get_similar_code_result_when_the_answer_is_not_json_reports_it_as_unreadable(
    make_tool: ToolFactory,
) -> None:
    """Verify that a proxy error page is not parsed as a result."""
    api = FakeApi(search_response=httpx.Response(200, content=b"<html>gateway</html>"))

    with pytest.raises(ToolError, match="unreadable"):
        await make_tool(api).get_similar_code_result(SEARCH_ID)


UNREADABLE_SEARCH_PAYLOADS = [
    {"status": "completed"},
    search_payload(status="archived"),
    search_payload(status="completed", incidents=[{**INCIDENT, "priority": "urgent"}]),
    search_payload(status="completed", incidents=[{"priority": "high"}]),
    search_payload(status="completed", incidents="not a list"),
]


@pytest.mark.parametrize("payload", UNREADABLE_SEARCH_PAYLOADS)
@pytest.mark.asyncio
async def test_get_similar_code_result_when_the_payload_is_unexpected_reports_a_tool_error(
    make_tool: ToolFactory, payload: dict[str, Any]
) -> None:
    """Verify that a malformed answer is reported as such, never passed to the LLM half-parsed."""
    with pytest.raises(ToolError, match="unexpected answer"):
        await make_tool(polled_with(payload)).get_similar_code_result(SEARCH_ID)


async def _listed_tool(name: str) -> Any:
    async with Client(mcp) as client:
        result = await client.list_tools()
    return next(tool for tool in result.tools if tool.name == name)


@pytest.mark.parametrize("name", ["find_similar_code", "get_similar_code_result"])
@pytest.mark.asyncio
async def test_server_lists_the_similar_code_tools(name: str) -> None:
    """Verify that connecting clients are told both tools exist."""
    tool = await _listed_tool(name)

    assert tool.name == name


@pytest.mark.asyncio
async def test_find_similar_code_is_not_annotated_as_idempotent() -> None:
    """Verify that clients are told a repeated call starts another billed search."""
    tool = await _listed_tool("find_similar_code")

    assert tool.annotations.idempotent_hint is False


@pytest.mark.asyncio
async def test_find_similar_code_is_annotated_as_not_read_only() -> None:
    """Verify that clients are told the tool changes state by starting a search."""
    tool = await _listed_tool("find_similar_code")

    assert tool.annotations.read_only_hint is False


@pytest.mark.asyncio
async def test_get_similar_code_result_is_annotated_as_read_only() -> None:
    """Verify that clients are told polling is free and changes nothing."""
    tool = await _listed_tool("get_similar_code_result")

    assert tool.annotations.read_only_hint is True


@pytest.mark.asyncio
async def test_find_similar_code_description_names_the_tool_to_poll_and_the_one_to_index_with() -> None:
    """Verify that the model reads, before calling, how to get the answer and what an unindexed repo needs."""
    tool = await _listed_tool("find_similar_code")

    assert "get_similar_code_result" in tool.description and "index_repo" in tool.description


@pytest.mark.asyncio
async def test_get_similar_code_result_description_warns_that_findings_are_untrusted() -> None:
    """Verify that the model is told findings quote repo code and must not be obeyed."""
    tool = await _listed_tool("get_similar_code_result")

    assert "untrusted" in tool.description
