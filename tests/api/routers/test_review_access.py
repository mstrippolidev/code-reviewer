"""
    Tests for who may read a review, through GET /api/reviews/{id} with the real access dependency.

    Only the DB session and GitHub are faked; tokens are really signed and verified.
"""
import uuid
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.oauth_token import OAuthToken
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import GUEST_SESSION_COOKIE, USER_SESSION_COOKIE, get_jwt_service, get_repo_access_checker
from api.exception_handlers import register_repo_exception_handlers
from api.repos.errors import GitHubAuthorizationExpiredError, GitHubVerificationUnavailableError
from api.routers.reviews import router as reviews_router
from api.security.jwt_service import JwtTokenService
from tests.api.fake_repo_access import FakeRepoAccessChecker

USER_ID = 1
GUEST_ID = 5
OTHER_GUEST_ID = 6

JWT_SERVICE = JwtTokenService(
    secret_key="review-access-test-secret-key-32-bytes", access_token_ttl_seconds=3600, state_token_ttl_seconds=300
)


class FakeSession:
    def __init__(self, job: ReviewJob | None, repo: RegisteredRepo | None, user: User | None) -> None:
        self._job = job
        self._repo = repo
        self._user = user

    async def scalar(self, statement) -> ReviewJob | RegisteredRepo | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is OAuthToken:
            return None
        return self._job if entity is ReviewJob else self._repo

    async def get(self, _model, _row_id: int) -> User | None:
        return self._user

    async def close(self) -> None:
        return None


class FakeDatabaseEngine:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def new_session(self) -> FakeSession:
        return self._session


def _repo_review(**overrides) -> ReviewJob:
    defaults = {
        "id": 1,
        "review_id": uuid.uuid4(),
        "repo_id": 10,
        "requested_by_user_id": USER_ID,
        "guest_session_id": None,
        "file_paths": ["a.py"],
        "status": ReviewJobStatus.COMPLETED,
        "status_reason": None,
        "result": None,
        "created_at": datetime(2026, 1, 1),
        "completed_at": None,
    }
    defaults.update(overrides)
    return ReviewJob(**defaults)


def _guest_review(guest_session_id: int = GUEST_ID) -> ReviewJob:
    return _repo_review(repo_id=None, requested_by_user_id=None, guest_session_id=guest_session_id)


def _repoless_review(requested_by_user_id: int = USER_ID) -> ReviewJob:
    return _repo_review(repo_id=None, requested_by_user_id=requested_by_user_id)


def _registered_repo() -> RegisteredRepo:
    return RegisteredRepo(id=1, repo_id=10, full_name="octocat/hello-world")


def _user() -> User:
    return User(id=USER_ID, encrypted_github_token="unused")


def _client(
    job: ReviewJob | None,
    *,
    checker: FakeRepoAccessChecker | None = None,
    repo: RegisteredRepo | None = None,
    user: User | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(reviews_router)
    register_repo_exception_handlers(app)
    app.state.database_engine = FakeDatabaseEngine(FakeSession(job, repo or _registered_repo(), user or _user()))
    app.dependency_overrides[get_jwt_service] = lambda: JWT_SERVICE
    app.dependency_overrides[get_repo_access_checker] = lambda: checker or FakeRepoAccessChecker()
    return TestClient(app)


def _as_user(client: TestClient, user_id: int = USER_ID) -> dict[str, str]:
    return {"Authorization": f"Bearer {JWT_SERVICE.issue_access_token(user_id=user_id)}"}


def _as_guest(client: TestClient, guest_session_id: int = GUEST_ID) -> None:
    client.cookies.set(GUEST_SESSION_COOKIE, JWT_SERVICE.issue_guest_session_token(guest_session_id=guest_session_id))


def _get(client: TestClient, job: ReviewJob, headers: dict[str, str] | None = None):
    return client.get(f"/api/reviews/{job.review_id}", headers=headers)


def test_guest_reads_their_own_review() -> None:
    """Verify that a guest can open the review their own session created."""
    job = _guest_review()
    client = _client(job)
    _as_guest(client)

    assert _get(client, job).status_code == 200


def test_guest_cannot_read_another_guests_review() -> None:
    """Verify that a guest session cannot read a review made by a different guest session."""
    job = _guest_review(OTHER_GUEST_ID)
    client = _client(job)
    _as_guest(client)

    assert _get(client, job).status_code == 404


def test_guest_cannot_read_a_repo_review() -> None:
    """Verify that a guest never reaches a review that belongs to a real user's repo."""
    job = _repo_review()
    client = _client(job)
    _as_guest(client)

    assert _get(client, job).status_code == 404


def test_guest_never_triggers_a_github_check() -> None:
    """Verify that refusing a guest costs no GitHub call."""
    job = _repo_review()
    checker = FakeRepoAccessChecker()
    client = _client(job, checker=checker)
    _as_guest(client)

    _get(client, job)

    assert checker.calls == []


def test_user_reads_a_review_of_a_repo_github_shows_them() -> None:
    """Verify that a logged-in user can open a repo review when the access check passes."""
    job = _repo_review()
    client = _client(job)

    assert _get(client, job, _as_user(client)).status_code == 200


def test_user_with_only_a_session_cookie_reads_a_review_of_a_repo_github_shows_them() -> None:
    """Verify that a web login (cookie, no Authorization header) opens reviews like a bearer token does."""
    job = _repo_review()
    client = _client(job)
    client.cookies.set(USER_SESSION_COOKIE, JWT_SERVICE.issue_user_session_token(user_id=USER_ID))

    assert _get(client, job).status_code == 200


def test_user_cannot_read_a_review_of_a_repo_github_hides_from_them() -> None:
    """Verify that losing access to the repo on GitHub also closes its reviews."""
    job = _repo_review()
    client = _client(job, checker=FakeRepoAccessChecker(denies=True))

    assert _get(client, job, _as_user(client)).status_code == 404


def test_user_asks_the_checker_about_the_reviews_repo() -> None:
    """Verify that the access check is about the repo the review belongs to, for the calling user."""
    job = _repo_review(repo_id=10)
    checker = FakeRepoAccessChecker()
    client = _client(job, checker=checker)

    _get(client, job, _as_user(client))

    assert checker.calls == [(USER_ID, 10)]


def test_user_cannot_read_a_guest_review() -> None:
    """Verify that a logged-in user cannot open a guest's review."""
    job = _guest_review()
    client = _client(job)

    assert _get(client, job, _as_user(client)).status_code == 404


def test_user_asking_for_a_guest_review_costs_no_github_call() -> None:
    """Verify that a guest review has no repo to check, so GitHub is not asked."""
    job = _guest_review()
    checker = FakeRepoAccessChecker()
    client = _client(job, checker=checker)

    _get(client, job, _as_user(client))

    assert checker.calls == []


def test_user_reads_their_own_repoless_review() -> None:
    """Verify that the user who submitted raw files can open the review, though it belongs to no repo."""
    job = _repoless_review()
    client = _client(job)

    assert _get(client, job, _as_user(client)).status_code == 200


def test_user_reading_their_own_repoless_review_costs_no_github_call() -> None:
    """Verify that a review with no repo has nothing to check on GitHub."""
    job = _repoless_review()
    checker = FakeRepoAccessChecker()
    client = _client(job, checker=checker)

    _get(client, job, _as_user(client))

    assert checker.calls == []


def test_user_cannot_read_another_users_repoless_review() -> None:
    """Verify that raw files one user submitted are private to that user."""
    job = _repoless_review(requested_by_user_id=USER_ID + 1)
    client = _client(job)

    assert _get(client, job, _as_user(client)).status_code == 404


def test_guest_cannot_read_a_users_repoless_review() -> None:
    """Verify that a guest session never reaches a logged-in user's raw-file review."""
    job = _repoless_review()
    client = _client(job)
    _as_guest(client)

    assert _get(client, job).status_code == 404


@pytest.mark.parametrize("suffix", ["", "/files/content?file_path=a.py", "/stream"], ids=["report", "content", "stream"])
def test_every_review_read_route_refuses_another_user_for_a_repoless_review(suffix: str) -> None:
    """Verify that the report, the file content and the live stream of a repoless review all stay private."""
    job = _repoless_review(requested_by_user_id=USER_ID + 1)
    client = _client(job)

    response = client.get(f"/api/reviews/{job.review_id}{suffix}", headers=_as_user(client))

    assert response.status_code == 404


def test_unknown_review_answers_404() -> None:
    """Verify that a review id nobody created answers 404."""
    client = _client(None)

    response = client.get(f"/api/reviews/{uuid.uuid4()}", headers=_as_user(client))

    assert response.status_code == 404


def test_denied_and_unknown_reviews_answer_the_same_way() -> None:
    """Verify that a stranger cannot tell a review they may not read from one that does not exist."""
    job = _repo_review()
    denied = _client(job, checker=FakeRepoAccessChecker(denies=True))
    unknown = _client(None)

    denied_body = _get(denied, job, _as_user(denied)).json()
    unknown_body = _get(unknown, job, _as_user(unknown)).json()

    assert denied_body == unknown_body


def test_request_without_credentials_answers_401() -> None:
    """Verify that a review is never served to a caller who is neither a user nor a guest."""
    job = _repo_review()

    assert _get(_client(job), job).status_code == 401


def test_request_with_a_garbage_bearer_token_answers_401() -> None:
    """Verify that an unverifiable token counts as no credentials at all."""
    job = _repo_review()

    response = _get(_client(job), job, {"Authorization": "Bearer not-a-token"})

    assert response.status_code == 401


def test_user_session_token_is_not_accepted_as_an_access_token() -> None:
    """Verify that a token issued for another purpose cannot be replayed to read reviews."""
    job = _repo_review()
    headers = {"Authorization": f"Bearer {JWT_SERVICE.issue_user_session_token(user_id=USER_ID)}"}

    assert _get(_client(job), job, headers).status_code == 401


def test_user_whose_account_no_longer_exists_answers_404() -> None:
    """Verify that a valid token for a deleted user cannot read anything."""
    job = _repo_review()
    client = _client(job)
    client.app.state.database_engine = FakeDatabaseEngine(FakeSession(job, _registered_repo(), None))

    assert _get(client, job, _as_user(client)).status_code == 404


def test_review_whose_repo_was_deleted_answers_404() -> None:
    """Verify that a review left behind by a deleted repo is not readable through a stale repo id."""
    job = _repo_review()
    client = _client(job)
    client.app.state.database_engine = FakeDatabaseEngine(FakeSession(job, None, _user()))

    assert _get(client, job, _as_user(client)).status_code == 404


def test_caller_with_both_credentials_reads_their_own_guest_review_even_if_github_denies() -> None:
    """Verify that either credential is enough: the guest cookie opens the guest's own review."""
    job = _guest_review()
    client = _client(job, checker=FakeRepoAccessChecker(denies=True))
    _as_guest(client)

    assert _get(client, job, _as_user(client)).status_code == 200


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (GitHubAuthorizationExpiredError("log in again"), 401),
        (GitHubVerificationUnavailableError("github is down"), 502),
    ],
)
def test_github_failure_while_checking_a_review_keeps_its_own_status(error: Exception, expected_status: int) -> None:
    """Verify that an expired GitHub token asks for a new login and an outage is a bad gateway, not a 404."""
    job = _repo_review()
    client = _client(job, checker=FakeRepoAccessChecker(error=error))

    assert _get(client, job, _as_user(client)).status_code == expected_status


@pytest.mark.parametrize("suffix", ["", "/files/content?file_path=a.py", "/stream"], ids=["report", "content", "stream"])
def test_every_review_read_route_refuses_a_user_github_denies(suffix: str) -> None:
    """Verify that the report, the file content and the live stream are all behind the same access rule."""
    job = _repo_review()
    client = _client(job, checker=FakeRepoAccessChecker(denies=True))

    response = client.get(f"/api/reviews/{job.review_id}{suffix}", headers=_as_user(client))

    assert response.status_code == 404
