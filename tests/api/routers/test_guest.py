"""
    Tests for the /api/guest routes and the shared user-or-guest read guard, against fakes:
    no real DB, no real Kafka.
"""
from datetime import datetime

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.db.models.guest_review_file import GuestReviewFile
from api.db.models.guest_session import GuestSession
from api.db.models.review_job import ReviewJob
from api.dependencies import (
    GUEST_SESSION_COOKIE,
    get_db_session,
    get_jwt_service,
    get_kafka_producer,
    require_user_or_guest,
)
from api.routers.guest import router as guest_router
from api.schemas.reviews import ReviewRequestedMessage
from api.security.jwt_service import JwtTokenService

_GUEST_SESSION_ID = 7


class FakeReviewProducer:
    def __init__(self) -> None:
        self.published: list[ReviewRequestedMessage] = []

    async def publish(self, topic: str, message: ReviewRequestedMessage, key: bytes) -> None:
        self.published.append(message)


class FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if isinstance(row, ReviewJob) and row.id is None:
                row.id = 1

    async def commit(self) -> None:
        pass

    async def refresh(self, row: object) -> None:
        if isinstance(row, GuestSession):
            row.id = _GUEST_SESSION_ID
        if isinstance(row, ReviewJob):
            row.created_at = datetime(2026, 1, 1)

    async def get(self, model: type, row_id: int) -> object | None:
        return GuestSession(id=row_id) if model is GuestSession and row_id == _GUEST_SESSION_ID else None


@pytest.fixture
def jwt_service() -> JwtTokenService:
    return JwtTokenService(secret_key="guest-router-test-secret-key", access_token_ttl_seconds=3600, state_token_ttl_seconds=300)


@pytest.fixture
def producer() -> FakeReviewProducer:
    return FakeReviewProducer()


@pytest.fixture
def session() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def client(jwt_service: JwtTokenService, producer: FakeReviewProducer, session: FakeAsyncSession) -> TestClient:
    app = FastAPI()
    app.include_router(guest_router)

    @app.get("/probe")
    def probe(_identity: None = Depends(require_user_or_guest)) -> dict:
        return {}

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_kafka_producer] = lambda: producer
    app.dependency_overrides[get_jwt_service] = lambda: jwt_service
    return TestClient(app)


def _guest_cookie(jwt_service: JwtTokenService) -> dict[str, str]:
    return {GUEST_SESSION_COOKIE: jwt_service.issue_guest_session_token(guest_session_id=_GUEST_SESSION_ID)}


def _files(count: int = 1) -> dict:
    return {"files": [{"file_path": f"f{index}.py", "content": "x = 1\n"} for index in range(count)]}


def test_start_guest_session_sets_a_verifiable_session_cookie(client: TestClient, jwt_service: JwtTokenService) -> None:
    response = client.post("/api/guest/session")

    assert jwt_service.verify_guest_session_token(response.cookies[GUEST_SESSION_COOKIE]) == _GUEST_SESSION_ID


def test_start_guest_session_cookie_is_http_only(client: TestClient) -> None:
    """Verify page scripts can't read the guest token, so an XSS can't lift it."""
    response = client.post("/api/guest/session")

    assert "httponly" in response.headers["set-cookie"].lower()


def test_submit_guest_review_publishes_a_guest_message(
    client: TestClient, jwt_service: JwtTokenService, producer: FakeReviewProducer
) -> None:
    client.post("/api/guest/review", json=_files(), cookies=_guest_cookie(jwt_service))

    [message] = producer.published
    assert message.guest_session_id == _GUEST_SESSION_ID


def test_submit_guest_review_stores_each_files_content_against_the_job(
    client: TestClient, jwt_service: JwtTokenService, session: FakeAsyncSession
) -> None:
    """Verify the submitted source is persisted, since the consumer and annotated view read it back later."""
    client.post("/api/guest/review", json=_files(count=2), cookies=_guest_cookie(jwt_service))

    stored = [(row.review_job_id, row.file_path, row.content) for row in session.added if isinstance(row, GuestReviewFile)]
    assert stored == [(1, "f0.py", "x = 1\n"), (1, "f1.py", "x = 1\n")]


def test_submit_guest_review_creates_a_job_with_no_repo_or_github_user(
    client: TestClient, jwt_service: JwtTokenService, session: FakeAsyncSession
) -> None:
    client.post("/api/guest/review", json=_files(), cookies=_guest_cookie(jwt_service))

    [job] = [row for row in session.added if isinstance(row, ReviewJob)]
    assert (job.repo_id, job.requested_by_user_id, job.guest_session_id) == (None, None, _GUEST_SESSION_ID)


def test_submit_guest_review_without_a_session_cookie_is_unauthorized(client: TestClient) -> None:
    response = client.post("/api/guest/review", json=_files())

    assert response.status_code == 401


def test_submit_guest_review_rejects_more_than_five_files(client: TestClient, jwt_service: JwtTokenService) -> None:
    response = client.post("/api/guest/review", json=_files(count=6), cookies=_guest_cookie(jwt_service))

    assert response.status_code == 422


def test_user_or_guest_guard_admits_a_guest_cookie(client: TestClient, jwt_service: JwtTokenService) -> None:
    response = client.get("/probe", cookies=_guest_cookie(jwt_service))

    assert response.status_code == 200


def test_user_or_guest_guard_admits_a_bearer_token(client: TestClient, jwt_service: JwtTokenService) -> None:
    token = jwt_service.issue_access_token(user_id=1)

    response = client.get("/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_user_or_guest_guard_rejects_a_request_with_neither(client: TestClient) -> None:
    response = client.get("/probe")

    assert response.status_code == 401


def test_user_or_guest_guard_rejects_an_invalid_bearer_token_with_no_cookie(client: TestClient) -> None:
    response = client.get("/probe", headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401
