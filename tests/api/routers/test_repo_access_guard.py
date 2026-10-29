"""
    Tests that every route acting on a registered repo is behind the GitHub access guard.

    The guard's own decisions are covered in tests/api/repos/test_access.py; these cover that
    each route consults it, answers what it decided, and does nothing when it says no.
"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_kafka_producer,
    get_repo_access_checker,
    get_repo_lifecycle_service,
)
from api.exception_handlers import register_repo_exception_handlers
from api.repos.errors import GitHubAuthorizationExpiredError, GitHubVerificationUnavailableError
from api.routers.repos import router as repos_router
from api.routers.reviews import router as reviews_router
from api.security.rate_limit_dependencies import get_rate_limiter
from tests.api.fake_rate_limit import AllowAllRateLimiter
from tests.api.fake_repo_access import FakeRepoAccessChecker

USER_ID = 7
REPO_ID = 10
UNREGISTERED_REPO_ID = 99

REPO_ROUTES = [
    ("get", f"/api/repos/{REPO_ID}/files", None),
    ("get", f"/api/repos/{REPO_ID}/files/content?file_path=a.py", None),
    ("get", f"/api/repos/{REPO_ID}/files/stream", None),
    ("post", f"/api/repos/{REPO_ID}/pause", None),
    ("post", f"/api/repos/{REPO_ID}/resume", None),
    ("post", f"/api/repos/{REPO_ID}/files/retry", None),
    ("delete", f"/api/repos/{REPO_ID}", None),
    ("post", f"/api/repos/{REPO_ID}/branch", {"branch": "develop"}),
    ("post", f"/api/repos/{REPO_ID}/review", {"file_paths": ["a.py"]}),
]
MUTATING_ROUTES = [route for route in REPO_ROUTES if route[0] in {"post", "delete"}]


class FakeSession:
    def __init__(self, repos: list[RegisteredRepo]) -> None:
        self._repos = repos

    async def scalar(self, statement) -> RegisteredRepo | None:
        repo_id = next(iter(statement.compile().params.values()))
        return next((repo for repo in self._repos if repo.repo_id == repo_id), None)

    async def close(self) -> None:
        return None


class RecordingLifecycleService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def pause(self, repo: RegisteredRepo, user: User) -> None:
        self.calls.append("pause")

    async def resume(self, repo: RegisteredRepo, user: User) -> None:
        self.calls.append("resume")

    async def retry_failed_files(self, repo: RegisteredRepo, user: User) -> None:
        self.calls.append("retry_failed_files")

    async def delete(self, repo: RegisteredRepo, user: User) -> None:
        self.calls.append("delete")

    async def switch_branch(self, repo: RegisteredRepo, branch: str, user: User) -> None:
        self.calls.append("switch_branch")


class RecordingProducer:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, topic: str, message: object, key: bytes) -> None:
        self.published.append(message)


def _registered_repo(status: RepoIndexStatus = RepoIndexStatus.INDEXING) -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=REPO_ID,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        branch="main",
        commit_sha=None,
        registered_by_user_id=1,
        status=status,
        created_at=datetime(2026, 1, 1),
    )


def _build_client(
    checker: FakeRepoAccessChecker,
    service: RecordingLifecycleService | None = None,
    producer: RecordingProducer | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(repos_router)
    app.include_router(reviews_router)
    register_repo_exception_handlers(app)

    async def _fake_db_session():
        yield FakeSession([_registered_repo()])

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_current_user] = lambda: User(id=USER_ID, encrypted_github_token="unused")
    app.dependency_overrides[get_repo_access_checker] = lambda: checker
    app.dependency_overrides[get_repo_lifecycle_service] = lambda: service or RecordingLifecycleService()
    app.dependency_overrides[get_kafka_producer] = lambda: producer or RecordingProducer()
    app.dependency_overrides[get_rate_limiter] = lambda: AllowAllRateLimiter()
    return TestClient(app)


def _call(client: TestClient, route: tuple[str, str, dict | None]):
    method, path, body = route
    return client.request(method, path, json=body)


@pytest.mark.parametrize("route", REPO_ROUTES, ids=[f"{method} {path}" for method, path, _ in REPO_ROUTES])
def test_repo_route_answers_404_when_the_caller_is_denied(route: tuple[str, str, dict | None]) -> None:
    """Verify that no route acting on a registered repo is reachable without GitHub access to it."""
    client = _build_client(FakeRepoAccessChecker(denies=True))

    response = _call(client, route)

    assert response.status_code == 404


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=[f"{method} {path}" for method, path, _ in MUTATING_ROUTES])
def test_repo_route_does_nothing_when_the_caller_is_denied(route: tuple[str, str, dict | None]) -> None:
    """Verify that a denied caller cannot pause, resume, retry, delete, switch branch or queue a review."""
    service = RecordingLifecycleService()
    producer = RecordingProducer()
    client = _build_client(FakeRepoAccessChecker(denies=True), service, producer)

    _call(client, route)

    assert service.calls == [] and producer.published == []


@pytest.mark.parametrize("route", REPO_ROUTES, ids=[f"{method} {path}" for method, path, _ in REPO_ROUTES])
def test_repo_route_asks_the_guard_about_the_caller_and_the_repo(route: tuple[str, str, dict | None]) -> None:
    """Verify that the guard is consulted with the authenticated user and the repo named in the path."""
    checker = FakeRepoAccessChecker(error=GitHubVerificationUnavailableError("stop here"))
    client = _build_client(checker)

    _call(client, route)

    assert checker.calls == [(USER_ID, REPO_ID)]


def test_unregistered_repo_answers_404_without_asking_github() -> None:
    """Verify that a repo id nobody registered costs no GitHub call."""
    checker = FakeRepoAccessChecker()
    client = _build_client(checker)

    response = client.get(f"/api/repos/{UNREGISTERED_REPO_ID}/files")

    assert response.status_code == 404 and checker.calls == []


@pytest.mark.parametrize(
    "error,expected_status",
    [
        (GitHubAuthorizationExpiredError("log in again"), 401),
        (GitHubVerificationUnavailableError("github is down"), 502),
    ],
)
def test_repo_route_maps_a_guard_failure_to_its_http_status(error: Exception, expected_status: int) -> None:
    """Verify that an expired GitHub token asks for a new login and a GitHub outage is a bad gateway."""
    client = _build_client(FakeRepoAccessChecker(error=error))

    response = client.get(f"/api/repos/{REPO_ID}/files")

    assert response.status_code == expected_status


def test_repo_by_name_answers_404_for_an_unknown_name_without_asking_github() -> None:
    """Verify that looking up a name nobody registered costs no GitHub call."""
    checker = FakeRepoAccessChecker()
    client = _build_client(checker)

    response = client.get("/api/repos/name", params={"full_name": "nobody/nothing"})

    assert response.status_code == 404 and checker.calls == []
