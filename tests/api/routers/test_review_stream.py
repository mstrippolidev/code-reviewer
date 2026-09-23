"""
    Tests for GET /api/reviews/{review_id}/stream against fakes: no real DB, no real Kafka.

    Uses httpx.AsyncClient + ASGITransport, same as test_repo_stream.py, since publishing an
    agent-progress event while the stream is still open requires running the client read as its
    own asyncio task rather than a single blocking call.
"""
import asyncio
import json
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster
from api.routers.reviews import router as reviews_router
from api.schemas.reviews import ReviewAgentProgressMessage, ReviewStatusMessage
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey

_TIMEOUT = 2


class FakeAsyncSession:
    def __init__(self, review_job: ReviewJob | None = None) -> None:
        self.review_job = review_job

    async def scalar(self, statement) -> ReviewJob | None:
        return self.review_job


def _make_review_job(**overrides) -> ReviewJob:
    defaults = {
        "id": 1,
        "review_id": uuid.uuid4(),
        "repo_id": 10,
        "requested_by_user_id": 1,
        "file_paths": ["a.py"],
        "status": ReviewJobStatus.RUNNING,
        "status_reason": None,
        "result": None,
        "created_at": datetime(2026, 1, 1),
        "completed_at": None,
    }
    defaults.update(overrides)
    return ReviewJob(**defaults)


def _make_user() -> User:
    return User(id=1, github_id=1, github_username="octocat")


def _build_app(*, session: FakeAsyncSession, broadcaster: ReviewProgressBroadcaster | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(reviews_router)
    app.state.review_progress_broadcaster = broadcaster or ReviewProgressBroadcaster()

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    return app


def _client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_events(text: str) -> list[dict]:
    events = []
    event_type = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append({"type": event_type, "data": json.loads(line[len("data:") :].strip())})
        elif line == "":
            event_type = "message"
    return events


def _agent_events(text: str) -> list[dict]:
    return [event["data"] for event in _parse_events(text) if event["type"] == "agent"]


@pytest.mark.asyncio
async def test_stream_relays_a_live_agent_progress_event() -> None:
    job = _make_review_job()
    broadcaster = ReviewProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(review_job=job), broadcaster=broadcaster)
    entry = AgentReviewEntry(file_path="a.py", code_key=CodeKey.VAR, incidents=[], rating=100)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get(f"/api/reviews/{job.review_id}/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            job.review_id,
            ReviewAgentProgressMessage(review_id=job.review_id, file_path="a.py", code_key=CodeKey.VAR, entry=entry),
        )
        await broadcaster.publish(
            job.review_id,
            ReviewStatusMessage(
                review_id=job.review_id,
                repo_id=job.repo_id,
                status=ReviewJobStatus.COMPLETED,
                status_reason=None,
                file_paths=job.file_paths,
                result=None,
            ),
        )
        response = await asyncio.wait_for(task, timeout=_TIMEOUT)

    events = _agent_events(response.text)
    assert len(events) == 1
    assert events[0]["file_path"] == "a.py"
    assert events[0]["code_key"] == "VAR"
    assert events[0]["entry"]["rating"] == 100
