"""
    Tests for POST /api/pull-requests/review against a fake submission service: the route's own contract
    (validation, status codes, rate limit). What the service decides is covered in
    tests/api/review/test_pull_request_submission.py.
"""
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config.settings import get_api_settings
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import get_current_user
from api.exception_handlers import register_pull_request_exception_handlers, register_repo_exception_handlers
from api.repos.errors import GitHubAuthorizationExpiredError, InsufficientPythonError, TooManyIndexJobsError
from api.review.pull_request_dependencies import get_pull_request_submission_service
from api.review.pull_request_errors import (
    PullRequestBaseBranchError,
    PullRequestNotFoundError,
    PullRequestNotOpenError,
    PullRequestQueueError,
    PullRequestRepoNotReadyError,
    PullRequestTooLargeError,
    PullRequestUnavailableError,
)
from api.review.review_capacity import get_review_slot_keeper
from api.routers.pull_requests import router
from api.schemas.pull_requests import PullRequestReviewRequest
from api.security.rate_limit_dependencies import REVIEW_SUBMISSION_SCOPE, get_rate_limiter
from tests.api.fake_rate_limit import AllowAllRateLimiter
from tests.api.fake_review_slots import FakeSlotKeeper

PATH = "/api/pull-requests/review"
PR_URL = "https://github.com/acme/api/pull/7"
USER_ID = 1
REVIEW_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


class FakeService:
    def __init__(self, error: Exception | None = None, reason: str | None = None) -> None:
        self._error = error
        self._reason = reason
        self.calls: list[tuple[PullRequestReviewRequest, User]] = []

    async def submit(self, request: PullRequestReviewRequest, user: User) -> ReviewJob:
        self.calls.append((request, user))
        if self._error:
            raise self._error
        return ReviewJob(
            id=1,
            review_id=REVIEW_ID,
            repo_id=10,
            requested_by_user_id=user.id,
            file_paths=[],
            pr_number=7,
            head_sha="head-sha",
            agents=[agent.value for agent in request.agents] if request.agents else None,
            status=ReviewJobStatus.PENDING,
            status_reason=self._reason,
            result=None,
            agent_entries=None,
            created_at=datetime(2026, 1, 1),
        )


def _client(
    service: FakeService, limiter: AllowAllRateLimiter | None = None, slot_keeper: FakeSlotKeeper | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    register_repo_exception_handlers(app)
    register_pull_request_exception_handlers(app)
    app.dependency_overrides[get_current_user] = lambda: User(id=USER_ID, encrypted_github_token="unused")
    app.dependency_overrides[get_pull_request_submission_service] = lambda: service
    app.dependency_overrides[get_rate_limiter] = lambda: limiter or AllowAllRateLimiter()
    app.dependency_overrides[get_review_slot_keeper] = lambda: slot_keeper or FakeSlotKeeper()
    return TestClient(app)


def test_submit_pull_request_review_answers_202_with_a_pending_job() -> None:
    """Verify the review is accepted at once, to be polled, not answered with a report."""
    response = _client(FakeService()).post(PATH, json={"pr_url": PR_URL})

    assert (response.status_code, response.json()["status"]) == (202, "pending")


def test_submit_pull_request_review_returns_the_id_to_poll_and_the_pinned_commit() -> None:
    """Verify the caller gets the review id for get_review, and the commit the review will cover."""
    body = _client(FakeService()).post(PATH, json={"pr_url": PR_URL}).json()

    assert (body["review_id"], body["pr_number"], body["head_sha"]) == (str(REVIEW_ID), 7, "head-sha")


def test_submit_pull_request_review_shows_why_a_job_is_waiting() -> None:
    """Verify a review waiting for its repo's index says so."""
    service = FakeService(reason="Waiting for the repo to finish indexing")

    body = _client(service).post(PATH, json={"pr_url": PR_URL}).json()

    assert body["status_reason"] == "Waiting for the repo to finish indexing"


def test_submit_pull_request_review_hands_the_request_and_the_caller_to_the_service() -> None:
    """Verify the service receives the parsed URL, the agent selection and the authenticated user."""
    service = FakeService()

    _client(service).post(PATH, json={"pr_url": PR_URL, "agents": ["TEST"]})

    request, user = service.calls[0]
    assert (request.pull_request.number, [agent.value for agent in request.agents], user.id) == (7, ["TEST"], USER_ID)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"pr_url": ""},
        {"pr_url": "https://gitlab.com/acme/api/pull/7"},
        {"pr_url": "https://github.com/acme/api"},
        {"pr_url": PR_URL, "agents": []},
        {"pr_url": PR_URL, "agents": ["NOPE"]},
    ],
)
def test_submit_pull_request_review_with_an_invalid_body_answers_422(body: dict) -> None:
    """Verify a bad URL or agent selection is refused before the service is asked to do anything."""
    service = FakeService()

    response = _client(service).post(PATH, json=body)

    assert (response.status_code, service.calls) == (422, [])


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (PullRequestNotFoundError("not found"), 404),
        (PullRequestNotOpenError(7), 422),
        (PullRequestTooLargeError(150, 100), 422),
        (PullRequestBaseBranchError("release", "main"), 422),
        (PullRequestRepoNotReadyError("failed"), 409),
        (PullRequestUnavailableError("github down"), 502),
        (PullRequestQueueError("not queued"), 502),
        (GitHubAuthorizationExpiredError("log in again"), 401),
        (InsufficientPythonError("not enough python"), 400),
        (TooManyIndexJobsError(3), 429),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, Exception) else str(value),
)
def test_submit_pull_request_review_maps_each_refusal_to_its_status(error: Exception, expected_status: int) -> None:
    """Verify every way a pull request can be refused reaches the caller with the right status."""
    response = _client(FakeService(error=error)).post(PATH, json={"pr_url": PR_URL})

    assert response.status_code == expected_status


def test_submit_pull_request_review_explains_a_refusal_in_the_detail() -> None:
    """Verify the message written for the user is what they receive."""
    response = _client(FakeService(error=PullRequestTooLargeError(150, 100))).post(PATH, json={"pr_url": PR_URL})

    assert response.json()["detail"] == "This pull request changes 150 files; at most 100 can be reviewed"


def test_submit_pull_request_review_counts_against_the_review_submission_limit() -> None:
    """Verify a pull request review spends the same per-user budget as any other review."""
    limiter = AllowAllRateLimiter()

    _client(FakeService(), limiter).post(PATH, json={"pr_url": PR_URL})

    expected_limit = get_api_settings().max_review_submissions_per_minute
    assert limiter.hits == [(REVIEW_SUBMISSION_SCOPE, USER_ID, expected_limit)]
