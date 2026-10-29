"""
    Tests that the rate limits are wired to the right routes with the configured numbers, and that going over
    a limit is answered as a 429 the client can act on.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.guest_session import GuestSession
from api.db.models.user import User
from api.exception_handlers import register_exception_handlers
from api.repos.errors import TooManyIndexJobsError
from api.routers.guest import router as guest_router
from api.routers.repos import router as repos_router
from api.routers.reviews import router as reviews_router
from api.security.rate_limit import RateLimitExceededError
from api.security.rate_limit_dependencies import (
    GUEST_REVIEW_SUBMISSION_SCOPE,
    REPO_REGISTRATION_SCOPE,
    REVIEW_SUBMISSION_SCOPE,
    limit_guest_review_submissions,
    limit_repo_registrations,
    limit_review_submissions,
)
from tests.api.fake_rate_limit import AllowAllRateLimiter

USER_ID = 4
GUEST_SESSION_ID = 9

CONFIGURED_LIMITS = SimpleNamespace(
    max_repo_registrations_per_minute=11,
    max_review_submissions_per_minute=12,
    max_guest_review_submissions_per_minute=13,
)


@pytest.fixture(autouse=True)
def configured_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.security.rate_limit_dependencies.get_api_settings", lambda: CONFIGURED_LIMITS)


def _user() -> User:
    return User(id=USER_ID, github_id=USER_ID, github_username="octocat", encrypted_github_token="x")


def _dependencies_of(router, path: str, method: str) -> list:
    [route] = [route for route in router.routes if route.path == path and method in route.methods]
    return [dependency.dependency for dependency in route.dependencies]


@pytest.mark.asyncio
async def test_repo_registrations_are_counted_per_user_against_their_configured_limit() -> None:
    limiter = AllowAllRateLimiter()

    await limit_repo_registrations(_user(), limiter)

    assert limiter.hits == [(REPO_REGISTRATION_SCOPE, USER_ID, 11)]


@pytest.mark.asyncio
async def test_review_submissions_are_counted_per_user_against_their_configured_limit() -> None:
    limiter = AllowAllRateLimiter()

    await limit_review_submissions(_user(), limiter)

    assert limiter.hits == [(REVIEW_SUBMISSION_SCOPE, USER_ID, 12)]


@pytest.mark.asyncio
async def test_guest_review_submissions_are_counted_per_guest_session_against_their_configured_limit() -> None:
    limiter = AllowAllRateLimiter()

    await limit_guest_review_submissions(GuestSession(id=GUEST_SESSION_ID), limiter)

    assert limiter.hits == [(GUEST_REVIEW_SUBMISSION_SCOPE, GUEST_SESSION_ID, 13)]


@pytest.mark.parametrize(
    ("router", "path", "limit"),
    [
        (repos_router, "/api/repos", limit_repo_registrations),
        (reviews_router, "/api/repos/{repo_id}/review", limit_review_submissions),
        (guest_router, "/api/guest/review", limit_guest_review_submissions),
    ],
    ids=["register", "review", "guest_review"],
)
def test_each_money_spending_route_carries_its_limit(router, path: str, limit) -> None:
    assert limit in _dependencies_of(router, path, "POST")


def _app_raising(error: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/spend")
    async def spend() -> None:
        raise error

    return TestClient(app)


def test_going_over_a_rate_limit_answers_429_with_retry_after() -> None:
    response = _app_raising(RateLimitExceededError(retry_after_seconds=12)).post("/spend")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "12"
    assert "12 seconds" in response.json()["detail"]


def test_going_over_the_unfinished_indexing_limit_answers_429_with_a_message_the_user_can_act_on() -> None:
    response = _app_raising(TooManyIndexJobsError(3)).post("/spend")

    assert response.status_code == 429
    assert "already have 3 repos being indexed" in response.json()["detail"]
