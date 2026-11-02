"""
    Tests for POST /api/repos/{repo_id}/similar-code and GET /api/similar-code/{search_id} against fakes:
    no real DB, no real Kafka. What the worker does with a queued search is covered in
    tests/api/similar_code/test_similar_code_consumer.py.
"""
import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config.settings import get_api_settings
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.similar_code_search import SimilarCodeSearch, SimilarCodeSearchStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session, get_kafka_producer, get_repo_access_checker
from api.indexing.producer import PublishError
from api.routers import similar_code as similar_code_module
from api.schemas.similar_code import SimilarCodeRequestedMessage
from api.security.rate_limit_dependencies import SIMILAR_CODE_SEARCH_SCOPE, get_rate_limiter
from api.similar_code.topics import SIMILAR_CODE_REQUESTED
from code_reviewer.config.settings import get_settings
from tests.api.fake_rate_limit import AllowAllRateLimiter
from tests.api.fake_repo_access import FakeRepoAccessChecker

SUBMIT_PATH = "/api/repos/10/similar-code"
SNIPPET = "def add(a, b):\n    return a + b\n"
USER_ID = 1
SEARCH_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
INCIDENT = {
    "priority": "high",
    "line_position": "1-2",
    "description": "add is structurally identical to legacy/ops.py:add.",
    "advice": "Extract the shared logic.",
}


class FakeProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[str, SimilarCodeRequestedMessage, bytes]] = []

    async def publish(self, topic: str, message: SimilarCodeRequestedMessage, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))


class FakeSession:
    """Blind to query shape except for the poll lookup, which only returns a search matching both ids in the query."""

    def __init__(self, *, repo: RegisteredRepo | None = None, search: SimilarCodeSearch | None = None) -> None:
        self.repo = repo
        self.search = search
        self.added: list[SimilarCodeSearch] = []
        self.commit_count = 0

    async def scalar(self, statement) -> object | None:
        if statement.column_descriptions[0]["entity"] is SimilarCodeSearch:
            return self._search_matching(statement)
        return self.repo

    def _search_matching(self, statement) -> SimilarCodeSearch | None:
        if self.search is None:
            return None
        asked_for = {str(value) for value in statement.compile().params.values()}
        owned_by_asker = {str(self.search.search_id), str(self.search.requested_by_user_id)} <= asked_for
        return self.search if owned_by_asker else None

    def add(self, row: SimilarCodeSearch) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, row: SimilarCodeSearch) -> None:
        if row.status is None:
            row.status = SimilarCodeSearchStatus.PENDING

    async def close(self) -> None:
        return None


def _make_repo(status: RepoIndexStatus = RepoIndexStatus.COMPLETED) -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        branch="main",
        commit_sha="abc123",
        registered_by_user_id=USER_ID,
        status=status,
        created_at=datetime(2026, 1, 1),
    )


def _make_search(**overrides) -> SimilarCodeSearch:
    defaults = {
        "id": 1,
        "search_id": SEARCH_ID,
        "repo_id": 10,
        "requested_by_user_id": USER_ID,
        "code": SNIPPET,
        "status": SimilarCodeSearchStatus.PENDING,
        "status_reason": None,
        "incidents": None,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return SimilarCodeSearch(**defaults)


def _build_client(
    session: FakeSession, producer: FakeProducer | None = None, limiter: AllowAllRateLimiter | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(similar_code_module.router)

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_current_user] = lambda: User(id=USER_ID, encrypted_github_token="unused")
    app.dependency_overrides[get_repo_access_checker] = lambda: FakeRepoAccessChecker()
    app.dependency_overrides[get_kafka_producer] = lambda: producer or FakeProducer()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter or AllowAllRateLimiter()
    return TestClient(app)


def _submit(client: TestClient, code: str = SNIPPET):
    return client.post(SUBMIT_PATH, json={"code": code})


def test_submit_similar_code_search_answers_202_pending() -> None:
    """Verify a submitted snippet is accepted at once, not answered with a result."""
    client = _build_client(FakeSession(repo=_make_repo()))

    response = _submit(client)

    assert (response.status_code, response.json()["status"]) == (202, "pending")


def test_submit_similar_code_search_returns_the_id_to_poll() -> None:
    """Verify the caller gets the search id that the poll route and the MCP tool use."""
    session = FakeSession(repo=_make_repo())

    response = _submit(_build_client(session))

    assert response.json()["search_id"] == str(session.added[0].search_id)


def test_submit_similar_code_search_stores_the_snippet_for_the_worker() -> None:
    """Verify the snippet is kept in the database, not sent through Kafka."""
    session = FakeSession(repo=_make_repo())

    _submit(_build_client(session))

    assert session.added[0].code == SNIPPET


def test_submit_similar_code_search_records_who_asked_and_for_which_repo() -> None:
    """Verify the row is owned by the caller and scoped to the repo in the path."""
    session = FakeSession(repo=_make_repo())

    _submit(_build_client(session))

    assert (session.added[0].requested_by_user_id, session.added[0].repo_id) == (USER_ID, 10)


def test_submit_similar_code_search_publishes_the_request_with_no_code() -> None:
    """Verify the worker is told which search to run, and the message carries only ids."""
    session = FakeSession(repo=_make_repo())
    producer = FakeProducer()

    _submit(_build_client(session, producer))

    topic, message, _key = producer.published[0]
    assert (topic, message) == (
        SIMILAR_CODE_REQUESTED,
        SimilarCodeRequestedMessage(search_id=session.added[0].search_id, repo_id=10),
    )


def test_submit_similar_code_search_for_a_repo_still_indexing_answers_409() -> None:
    """Verify a search over an incomplete index is refused rather than answered with partial results."""
    client = _build_client(FakeSession(repo=_make_repo(RepoIndexStatus.INDEXING)))

    response = _submit(client)

    assert response.status_code == 409


def test_submit_similar_code_search_for_a_repo_still_indexing_stores_and_queues_nothing() -> None:
    """Verify a refused search costs nothing and keeps no snippet."""
    session = FakeSession(repo=_make_repo(RepoIndexStatus.INDEXING))
    producer = FakeProducer()

    _submit(_build_client(session, producer))

    assert (session.added, producer.published) == ([], [])


def test_submit_similar_code_search_with_empty_code_answers_422() -> None:
    """Verify an empty snippet is rejected before anything is stored."""
    response = _submit(_build_client(FakeSession(repo=_make_repo())), code="")

    assert response.status_code == 422


def test_submit_similar_code_search_over_the_character_cap_answers_422() -> None:
    """Verify a snippet longer than the submission cap is rejected at the schema, before the pipeline."""
    oversized_code = "x" * (get_settings().max_submission_characters + 1)

    response = _submit(_build_client(FakeSession(repo=_make_repo())), code=oversized_code)

    assert response.status_code == 422


def test_submit_similar_code_search_when_kafka_refuses_answers_502() -> None:
    """Verify a search that could not be queued is reported, not left pending forever."""
    producer = FakeProducer(publish_error=PublishError("kafka down"))

    response = _submit(_build_client(FakeSession(repo=_make_repo()), producer))

    assert response.status_code == 502


def test_submit_similar_code_search_when_kafka_refuses_marks_it_failed_and_drops_the_snippet() -> None:
    """Verify user code is not left in the table for a search nobody will run."""
    session = FakeSession(repo=_make_repo())
    producer = FakeProducer(publish_error=PublishError("kafka down"))

    _submit(_build_client(session, producer))

    row = session.added[0]
    assert (row.status, row.status_reason, row.code) == (
        SimilarCodeSearchStatus.FAILED,
        similar_code_module.SEARCH_NOT_QUEUED_DETAIL,
        None,
    )


def test_submit_similar_code_search_counts_against_its_own_rate_limit() -> None:
    """Verify each search is charged to the caller under the similar-code scope, not the review budget."""
    limiter = AllowAllRateLimiter()

    _submit(_build_client(FakeSession(repo=_make_repo()), limiter=limiter))

    expected_limit = get_api_settings().max_similar_code_searches_per_minute
    assert limiter.hits == [(SIMILAR_CODE_SEARCH_SCOPE, USER_ID, expected_limit)]


def test_get_similar_code_search_returns_the_status_of_the_callers_search() -> None:
    """Verify a poller sees where its search stands."""
    client = _build_client(FakeSession(search=_make_search(status=SimilarCodeSearchStatus.RUNNING)))

    response = client.get(f"/api/similar-code/{SEARCH_ID}")

    assert response.json()["status"] == "running"


def test_get_similar_code_search_returns_the_incidents_once_completed() -> None:
    """Verify the finished answer reaches the poller."""
    search = _make_search(status=SimilarCodeSearchStatus.COMPLETED, incidents=[INCIDENT], code=None)

    response = _build_client(FakeSession(search=search)).get(f"/api/similar-code/{SEARCH_ID}")

    assert response.json()["incidents"][0]["description"] == INCIDENT["description"]


def test_get_similar_code_search_returns_the_reason_a_snippet_was_rejected() -> None:
    """Verify a poller learns why the snippet was refused, so it can fix it."""
    search = _make_search(status=SimilarCodeSearchStatus.REJECTED, status_reason="not source code", code=None)

    response = _build_client(FakeSession(search=search)).get(f"/api/similar-code/{SEARCH_ID}")

    assert response.json()["status_reason"] == "not source code"


def test_get_similar_code_search_never_returns_the_snippet() -> None:
    """Verify the stored code is not part of the response."""
    client = _build_client(FakeSession(search=_make_search()))

    response = client.get(f"/api/similar-code/{SEARCH_ID}")

    assert SNIPPET not in response.text


def test_get_similar_code_search_asked_by_another_user_answers_404() -> None:
    """Verify one user's pasted code and results cannot be read by another user."""
    client = _build_client(FakeSession(search=_make_search(requested_by_user_id=USER_ID + 1)))

    response = client.get(f"/api/similar-code/{SEARCH_ID}")

    assert response.status_code == 404


def test_get_similar_code_search_for_an_unknown_id_answers_404() -> None:
    """Verify a search that does not exist is a plain 404."""
    client = _build_client(FakeSession())

    response = client.get(f"/api/similar-code/{SEARCH_ID}")

    assert response.status_code == 404
