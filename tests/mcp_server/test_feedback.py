import json
import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from mcp_server.tools.feedback import FeedbackTools, FindingRating

REVIEW_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
API_BASE_URL = "http://api.test"

Handler = Callable[[httpx.Request], httpx.Response]
ToolFactory = Callable[[Handler], FeedbackTools]

STORED = {"incident_id": 7, "verdict": "down", "reason": "not_true", "note": None}


@pytest_asyncio.fixture
async def make_tool() -> AsyncIterator[ToolFactory]:
    clients: list[httpx.AsyncClient] = []

    def build(handler: Handler) -> FeedbackTools:
        client = httpx.AsyncClient(base_url=API_BASE_URL, transport=httpx.MockTransport(handler))
        clients.append(client)
        return FeedbackTools(client)

    yield build

    for client in clients:
        await client.aclose()


def respond_with(status_code: int, body: object) -> Handler:
    return lambda request: httpx.Response(status_code, json=body)


@pytest.mark.asyncio
async def test_rate_finding_puts_the_rating_on_the_reviews_feedback_path(make_tool: ToolFactory) -> None:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=STORED)

    rating = FindingRating(verdict="down", reason="not_true", note="that function is used")
    await make_tool(record).rate_finding(REVIEW_ID, 7, rating)

    assert (requests[0].method, requests[0].url.path) == ("PUT", f"/api/reviews/{REVIEW_ID}/feedback")
    assert json.loads(requests[0].content) == {
        "incident_id": 7,
        "verdict": "down",
        "reason": "not_true",
        "note": "that function is used",
    }


@pytest.mark.asyncio
async def test_rate_finding_returns_what_api_stored(make_tool: ToolFactory) -> None:
    recorded = await make_tool(respond_with(200, STORED)).rate_finding(REVIEW_ID, 7, FindingRating(verdict="down"))

    assert (recorded.incident_id, recorded.verdict, recorded.reason) == (7, "down", "not_true")


@pytest.mark.asyncio
async def test_an_incident_that_is_not_found_tells_the_model_where_to_get_a_real_id(make_tool: ToolFactory) -> None:
    tool = make_tool(respond_with(404, {"detail": "Incident not found in this review"}))

    with pytest.raises(ToolError, match="get_review"):
        await tool.rate_finding(REVIEW_ID, 999, FindingRating(verdict="up"))


@pytest.mark.asyncio
async def test_a_refused_rating_passes_on_the_field_errors(make_tool: ToolFactory) -> None:
    detail = [{"loc": ["body", "reason"], "msg": "Value error, A reason can only be given with a thumbs down"}]
    tool = make_tool(respond_with(422, {"detail": detail}))

    with pytest.raises(ToolError, match="reason: A reason can only be given with a thumbs down"):
        await tool.rate_finding(REVIEW_ID, 7, FindingRating(verdict="up"))


@pytest.mark.asyncio
async def test_an_expired_sign_in_says_to_sign_in_again(make_tool: ToolFactory) -> None:
    with pytest.raises(ToolError, match="Sign in again"):
        await make_tool(respond_with(401, {"detail": "expired"})).rate_finding(
            REVIEW_ID, 7, FindingRating(verdict="up")
        )


@pytest.mark.asyncio
async def test_a_server_failure_hides_the_internal_detail(make_tool: ToolFactory) -> None:
    tool = make_tool(respond_with(500, {"detail": "internal path /srv/secret"}))

    with pytest.raises(ToolError) as raised:
        await tool.rate_finding(REVIEW_ID, 7, FindingRating(verdict="up"))

    assert "secret" not in str(raised.value)


@pytest.mark.asyncio
async def test_an_unreachable_api_is_a_tool_error(make_tool: ToolFactory) -> None:
    def fail_to_connect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ToolError, match="unreachable"):
        await make_tool(fail_to_connect).rate_finding(REVIEW_ID, 7, FindingRating(verdict="up"))


@pytest.mark.asyncio
async def test_an_unreadable_answer_says_not_to_rate_again_at_once(make_tool: ToolFactory) -> None:
    tool = make_tool(lambda request: httpx.Response(200, content=b"not json"))

    with pytest.raises(ToolError, match="may have been recorded"):
        await tool.rate_finding(REVIEW_ID, 7, FindingRating(verdict="up"))


def test_a_note_longer_than_the_limit_is_refused_before_any_call() -> None:
    with pytest.raises(ValidationError):
        FindingRating(verdict="down", note="x" * 501)
