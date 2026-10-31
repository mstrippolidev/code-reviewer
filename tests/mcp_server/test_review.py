import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from mcp_server.tools.repo_status import HttpRepoStatusSource
from mcp_server.tools.review import REVIEW_PATH, ReviewReport, ReviewStatus, ReviewTools

REVIEW_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
API_BASE_URL = "http://api.test"

Handler = Callable[[httpx.Request], httpx.Response]
ToolFactory = Callable[[Handler], ReviewTools]


def review_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "review_id": str(REVIEW_ID),
        "repo_id": 42,
        "status": "completed",
        "status_reason": None,
        "file_paths": ["a.py", "b.py"],
        "result": {"overall_rating": 80},
        "agent_entries": {"a.py": {"VAR": {}}, "b.py": {"VAR": {}}},
    }
    return payload | overrides


def respond_with(payload: dict[str, Any]) -> Handler:
    return lambda request: httpx.Response(200, json=payload)


def respond_with_status(status_code: int) -> Handler:
    return lambda request: httpx.Response(status_code, json={"detail": "internal path /srv/secret"})


def fail_to_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


@pytest_asyncio.fixture
async def make_tool() -> AsyncIterator[ToolFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(handler: Handler) -> ReviewTools:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(handler))
        clients.append(client)
        return ReviewTools(client, HttpRepoStatusSource(client))

    yield build

    for client in clients:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_review_reads_the_review_path_with_the_given_id(make_tool: ToolFactory) -> None:
    """Verify that the tool asks api/ for exactly the review the caller named."""
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=review_payload())

    await make_tool(record).get_review(REVIEW_ID)

    assert (requests[0].method, requests[0].url.path) == ("GET", f"{REVIEW_PATH}/{REVIEW_ID}")


@pytest.mark.asyncio
async def test_get_review_of_a_completed_review_returns_the_merged_result(make_tool: ToolFactory) -> None:
    """Verify that a finished review hands the aggregated report to the LLM."""
    report = await make_tool(respond_with(review_payload())).get_review(REVIEW_ID)

    assert report.result == {"overall_rating": 80}


@pytest.mark.asyncio
async def test_get_review_reports_the_status_from_api(make_tool: ToolFactory) -> None:
    """Verify that the status is what tells the LLM whether to keep polling."""
    payload = review_payload(status="running", result=None)

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.status == ReviewStatus.RUNNING


@pytest.mark.asyncio
async def test_get_review_counts_the_submitted_files_as_the_total(make_tool: ToolFactory) -> None:
    """Verify that the total is the number of submitted files."""
    report = await make_tool(respond_with(review_payload())).get_review(REVIEW_ID)

    assert report.files_total == 2


@pytest.mark.asyncio
async def test_get_review_counts_files_with_entries_as_reviewed(make_tool: ToolFactory) -> None:
    """Verify that progress counts the files whose agent entries are already stored."""
    payload = review_payload(status="running", result=None, agent_entries={"a.py": {"VAR": {}}})

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.files_reviewed == 1


@pytest.mark.asyncio
async def test_get_review_before_any_file_finishes_reports_zero_reviewed(make_tool: ToolFactory) -> None:
    """Verify that a pending review, whose agent entries are still null, reports no progress."""
    payload = review_payload(status="pending", result=None, agent_entries=None)

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.files_reviewed == 0


@pytest.mark.asyncio
async def test_get_review_of_a_failed_review_carries_the_reason(make_tool: ToolFactory) -> None:
    """Verify that the LLM can tell the user why a review failed."""
    payload = review_payload(status="failed", status_reason="Provider timed out", result=None)

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.status_reason == "Provider timed out"


@pytest.mark.asyncio
async def test_get_review_does_not_expose_the_repo_id(make_tool: ToolFactory) -> None:
    """Verify that internal api/ fields outside the report model are not passed to the LLM."""
    report = await make_tool(respond_with(review_payload())).get_review(REVIEW_ID)

    assert "repo_id" not in report.model_dump()


@pytest.mark.asyncio
async def test_get_review_returns_the_per_file_agent_entries(make_tool: ToolFactory) -> None:
    """Verify that the findings of files that already finished reach the LLM unchanged."""
    payload = review_payload(status="running", result=None, agent_entries={"a.py": {"VAR": {"rating": 90}}})

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.agent_entries == {"a.py": {"VAR": {"rating": 90}}}


@pytest.mark.asyncio
async def test_get_review_with_no_submitted_files_reports_a_zero_total(make_tool: ToolFactory) -> None:
    """Verify that an empty file list gives a total of zero rather than an error."""
    payload = review_payload(file_paths=[], agent_entries={})

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.files_total == 0


@pytest.mark.asyncio
async def test_get_review_with_empty_agent_entries_reports_zero_reviewed(make_tool: ToolFactory) -> None:
    """Verify that an empty entries mapping, as opposed to null, also means no progress yet."""
    payload = review_payload(status="running", result=None, agent_entries={})

    report = await make_tool(respond_with(payload)).get_review(REVIEW_ID)

    assert report.files_reviewed == 0


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b""])
@pytest.mark.asyncio
async def test_get_review_when_api_sends_a_body_that_is_not_json_reports_a_tool_error(
    make_tool: ToolFactory, body: bytes
) -> None:
    """Verify that a 200 with a proxy error page or an empty body becomes a retry hint."""
    tool = make_tool(lambda request: httpx.Response(200, content=body))

    with pytest.raises(ToolError, match="unreadable answer"):
        await tool.get_review(REVIEW_ID)


@pytest.mark.parametrize("missing_key", ["status", "status_reason", "file_paths", "result", "agent_entries"])
@pytest.mark.asyncio
async def test_get_review_when_api_omits_a_field_reports_a_tool_error(
    make_tool: ToolFactory, missing_key: str
) -> None:
    """Verify that a payload missing a required field does not escape as a raw KeyError."""
    payload = review_payload()
    del payload[missing_key]

    with pytest.raises(ToolError, match="unexpected answer"):
        await make_tool(respond_with(payload)).get_review(REVIEW_ID)


@pytest.mark.parametrize("malformed_payload", [review_payload(file_paths=None), ["not", "an", "object"]])
@pytest.mark.asyncio
async def test_get_review_when_api_sends_the_wrong_shape_reports_a_tool_error(
    make_tool: ToolFactory, malformed_payload: Any
) -> None:
    """Verify that a null file list or a non-object body does not escape as a raw TypeError."""
    with pytest.raises(ToolError, match="unexpected answer"):
        await make_tool(respond_with(malformed_payload)).get_review(REVIEW_ID)


@pytest.mark.asyncio
async def test_get_review_when_api_sends_an_unknown_status_reports_a_tool_error(
    make_tool: ToolFactory,
) -> None:
    """Verify that a status api/ may add later is reported as an error, not passed on as free text."""
    tool = make_tool(respond_with(review_payload(status="archived")))

    with pytest.raises(ToolError, match="unexpected answer"):
        await tool.get_review(REVIEW_ID)


@pytest.mark.asyncio
async def test_get_review_for_an_unknown_review_names_the_id_in_the_error(make_tool: ToolFactory) -> None:
    """Verify that a 404 tells the LLM which id was not found and to check it."""
    tool = make_tool(respond_with_status(404))

    with pytest.raises(ToolError, match=f"Review '{REVIEW_ID}' was not found"):
        await tool.get_review(REVIEW_ID)


@pytest.mark.parametrize("status_code", [401, 500, 502])
@pytest.mark.asyncio
async def test_get_review_when_api_fails_tells_the_llm_to_retry(
    make_tool: ToolFactory, status_code: int
) -> None:
    """Verify that any other api/ failure becomes a retry hint rather than a raw error."""
    tool = make_tool(respond_with_status(status_code))

    with pytest.raises(ToolError, match="Try again shortly"):
        await tool.get_review(REVIEW_ID)


@pytest.mark.asyncio
async def test_get_review_when_api_fails_does_not_leak_the_api_error_body(make_tool: ToolFactory) -> None:
    """Verify that internal details from api/ never reach the calling LLM."""
    tool = make_tool(respond_with_status(500))

    with pytest.raises(ToolError) as raised:
        await tool.get_review(REVIEW_ID)

    assert "/srv/secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_get_review_when_api_is_unreachable_reports_a_tool_error(make_tool: ToolFactory) -> None:
    """Verify that a network failure surfaces as a ToolError, not a raw httpx error."""
    tool = make_tool(fail_to_connect)

    with pytest.raises(ToolError, match="unreachable"):
        await tool.get_review(REVIEW_ID)


def test_review_report_rejects_a_status_api_does_not_define() -> None:
    """Verify that an unknown status fails loudly instead of reaching the LLM as free text."""
    with pytest.raises(ValidationError):
        ReviewReport(
            status="archived",
            status_reason=None,
            files_total=1,
            files_reviewed=0,
            result=None,
            agent_entries=None,
        )
