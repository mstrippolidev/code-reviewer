"""
    Tests for the /api/repos/{repo_id}/review and /api/reviews routes against fakes:
    no real DB, no real Kafka.
"""
import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.guest_review_file import GuestReviewFile
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_kafka_producer,
    get_repo_access_checker,
    require_review_access,
)
from api.indexing.producer import PublishError
from api.routers.reviews import router as reviews_router
from api.schemas.reviews import ReviewRequestedMessage
from api.security.rate_limit_dependencies import get_rate_limiter
from tests.api.fake_rate_limit import AllowAllRateLimiter
from tests.api.fake_repo_access import FakeRepoAccessChecker


class FakeReviewProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[ReviewRequestedMessage] = []

    async def publish(self, topic: str, message: ReviewRequestedMessage, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append(message)


class _ScalarsResult:
    def __init__(self, items: list[str]) -> None:
        self._items = items

    def all(self) -> list[str]:
        return self._items


class FakeAsyncSession:
    """Blind to query shape, like the repos router's own fakes: seeded per test."""

    def __init__(
        self,
        *,
        registered_repo: RegisteredRepo | None = None,
        indexed_files: list[IndexedFile] | None = None,
        review_job: ReviewJob | None = None,
        guest_file: GuestReviewFile | None = None,
    ) -> None:
        self.registered_repo = registered_repo
        self.indexed_files = indexed_files or []
        self.review_job = review_job
        self.guest_file = guest_file
        self.added: list[object] = []

    async def scalar(self, statement) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is ReviewJob:
            return self.review_job
        if entity is GuestReviewFile:
            return self.guest_file
        return self.registered_repo

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult([file.file_path for file in self.indexed_files])

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if isinstance(row, ReviewJob) and row.id is None:
                row.id = 1

    async def commit(self) -> None:
        pass

    async def refresh(self, row: ReviewJob) -> None:
        if row.id is None:
            row.id = 1
        if row.created_at is None:
            row.created_at = datetime(2026, 1, 1)


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "branch": "main",
        "commit_sha": "abc123",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.COMPLETED,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


def _make_indexed_file(**overrides) -> IndexedFile:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "file_path": "src/module.py",
        "status": IndexedFileStatus.INDEXED,
        "content": "x = 1\n",
    }
    defaults.update(overrides)
    return IndexedFile(**defaults)


def _make_review_job(**overrides) -> ReviewJob:
    defaults = {
        "id": 1,
        "review_id": uuid.uuid4(),
        "repo_id": 10,
        "requested_by_user_id": 1,
        "file_paths": ["src/module.py"],
        "status": ReviewJobStatus.COMPLETED,
        "status_reason": None,
        "result": None,
        "created_at": datetime(2026, 1, 1),
        "completed_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return ReviewJob(**defaults)


def _make_user() -> User:
    return User(id=1, github_id=1, github_username="octocat")


def _build_app(*, session: FakeAsyncSession, kafka_producer: FakeReviewProducer | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(reviews_router)

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_kafka_producer] = lambda: kafka_producer or FakeReviewProducer()
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[require_review_access] = lambda: session.review_job
    app.dependency_overrides[get_repo_access_checker] = lambda: FakeRepoAccessChecker()
    app.dependency_overrides[get_rate_limiter] = lambda: AllowAllRateLimiter()
    return app


def test_submit_review_queues_a_job_for_indexed_files() -> None:
    repo = _make_registered_repo()
    files = [_make_indexed_file(file_path="a.py"), _make_indexed_file(file_path="b.py")]
    producer = FakeReviewProducer()
    app = _build_app(session=FakeAsyncSession(registered_repo=repo, indexed_files=files), kafka_producer=producer)
    client = TestClient(app)

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py", "b.py"]})

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert len(producer.published) == 1
    assert producer.published[0].file_paths == ["a.py", "b.py"]
    assert producer.published[0].repo_id == 10


def _indexed_session() -> FakeAsyncSession:
    return FakeAsyncSession(
        registered_repo=_make_registered_repo(), indexed_files=[_make_indexed_file(file_path="a.py")]
    )


def test_submit_review_without_agents_stores_no_restriction_on_the_job() -> None:
    session = _indexed_session()
    client = TestClient(_build_app(session=session))

    client.post("/api/repos/10/review", json={"file_paths": ["a.py"]})

    assert session.added[0].agents is None


def test_submit_review_without_agents_publishes_no_restriction() -> None:
    producer = FakeReviewProducer()
    client = TestClient(_build_app(session=_indexed_session(), kafka_producer=producer))

    client.post("/api/repos/10/review", json={"file_paths": ["a.py"]})

    assert producer.published[0].agents is None


def test_submit_review_stores_the_requested_agents_on_the_job() -> None:
    session = _indexed_session()
    client = TestClient(_build_app(session=session))

    client.post("/api/repos/10/review", json={"file_paths": ["a.py"], "agents": ["TEST", "TCASE"]})

    assert session.added[0].agents == ["TEST", "TCASE"]


def test_submit_review_publishes_the_requested_agents() -> None:
    producer = FakeReviewProducer()
    client = TestClient(_build_app(session=_indexed_session(), kafka_producer=producer))

    client.post("/api/repos/10/review", json={"file_paths": ["a.py"], "agents": ["TEST", "TCASE"]})

    assert [agent.value for agent in producer.published[0].agents] == ["TEST", "TCASE"]


def test_submit_review_returns_the_requested_agents() -> None:
    client = TestClient(_build_app(session=_indexed_session()))

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py"], "agents": ["TEST"]})

    assert response.json()["agents"] == ["TEST"]


def test_submit_review_with_an_unknown_agent_is_rejected() -> None:
    client = TestClient(_build_app(session=_indexed_session()))

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py"], "agents": ["NOPE"]})

    assert response.status_code == 422


def test_submit_review_with_an_unknown_agent_stores_nothing() -> None:
    session = _indexed_session()
    client = TestClient(_build_app(session=session))

    client.post("/api/repos/10/review", json={"file_paths": ["a.py"], "agents": ["NOPE"]})

    assert session.added == []


def test_get_review_returns_the_agents_the_review_was_restricted_to() -> None:
    job = _make_review_job(agents=["TEST"])
    client = TestClient(_build_app(session=FakeAsyncSession(review_job=job)))

    response = client.get(f"/api/reviews/{job.review_id}")

    assert response.json()["agents"] == ["TEST"]


def test_submit_review_rejects_files_that_are_not_indexed() -> None:
    repo = _make_registered_repo()
    files = [_make_indexed_file(file_path="a.py")]
    app = _build_app(session=FakeAsyncSession(registered_repo=repo, indexed_files=files))
    client = TestClient(app)

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py", "missing.py"]})

    assert response.status_code == 400


REPOLESS_FILES = [
    {"file_path": "src/a.py", "content": "def a():\n    return 1\n"},
    {"file_path": "tests/test_a.py", "content": "def test_a():\n    assert a() == 1\n"},
]


def _post_repoless(client: TestClient, **overrides):
    return client.post("/api/reviews", json={"files": REPOLESS_FILES} | overrides)


def test_submit_repoless_review_queues_a_pending_job() -> None:
    client = TestClient(_build_app(session=FakeAsyncSession()))

    response = _post_repoless(client)

    assert (response.status_code, response.json()["status"]) == (202, "pending")


def test_submit_repoless_review_stores_a_job_owned_by_the_user_with_no_repo() -> None:
    session = FakeAsyncSession()
    client = TestClient(_build_app(session=session))

    _post_repoless(client)

    job = session.added[0]
    assert (job.requested_by_user_id, job.repo_id, job.guest_session_id) == (1, None, None)


def test_submit_repoless_review_stores_each_files_content() -> None:
    session = FakeAsyncSession()
    client = TestClient(_build_app(session=session))

    _post_repoless(client)

    stored = [(row.file_path, row.content) for row in session.added if isinstance(row, GuestReviewFile)]
    assert stored == [(file["file_path"], file["content"]) for file in REPOLESS_FILES]


def test_submit_repoless_review_ties_the_stored_files_to_the_job() -> None:
    session = FakeAsyncSession()
    client = TestClient(_build_app(session=session))

    _post_repoless(client)

    job = session.added[0]
    assert {row.review_job_id for row in session.added if isinstance(row, GuestReviewFile)} == {job.id}


def test_submit_repoless_review_lists_the_file_paths_on_the_job() -> None:
    session = FakeAsyncSession()
    client = TestClient(_build_app(session=session))

    _post_repoless(client)

    assert session.added[0].file_paths == ["src/a.py", "tests/test_a.py"]


def test_submit_repoless_review_publishes_a_message_without_the_file_content() -> None:
    producer = FakeReviewProducer()
    client = TestClient(_build_app(session=FakeAsyncSession(), kafka_producer=producer))

    _post_repoless(client)

    message = producer.published[0]
    assert (message.requested_by_user_id, message.repo_id, message.file_paths) == (
        1,
        None,
        ["src/a.py", "tests/test_a.py"],
    )


def test_submit_repoless_review_publishes_a_message_the_consumer_loads_stored_files_for() -> None:
    producer = FakeReviewProducer()
    client = TestClient(_build_app(session=FakeAsyncSession(), kafka_producer=producer))

    _post_repoless(client)

    assert producer.published[0].has_uploaded_files is True


def test_submit_repoless_review_stores_and_publishes_the_requested_agents() -> None:
    session = FakeAsyncSession()
    producer = FakeReviewProducer()
    client = TestClient(_build_app(session=session, kafka_producer=producer))

    _post_repoless(client, agents=["TEST", "TCASE"])

    assert (session.added[0].agents, [agent.value for agent in producer.published[0].agents]) == (
        ["TEST", "TCASE"],
        ["TEST", "TCASE"],
    )


def test_submit_repoless_review_returns_the_requested_agents() -> None:
    client = TestClient(_build_app(session=FakeAsyncSession()))

    response = _post_repoless(client, agents=["TEST"])

    assert response.json()["agents"] == ["TEST"]


def test_submit_repoless_review_asking_for_dry_is_rejected() -> None:
    client = TestClient(_build_app(session=FakeAsyncSession()))

    response = _post_repoless(client, agents=["DRY"])

    assert response.status_code == 422


def test_submit_repoless_review_asking_for_dry_stores_nothing() -> None:
    session = FakeAsyncSession()
    client = TestClient(_build_app(session=session))

    _post_repoless(client, agents=["DRY"])

    assert session.added == []


def test_submit_repoless_review_with_no_files_is_rejected() -> None:
    client = TestClient(_build_app(session=FakeAsyncSession()))

    response = client.post("/api/reviews", json={"files": []})

    assert response.status_code == 422


def test_submit_repoless_review_when_the_queue_is_down_answers_502() -> None:
    producer = FakeReviewProducer(publish_error=PublishError("broker unreachable"))
    client = TestClient(_build_app(session=FakeAsyncSession(), kafka_producer=producer))

    response = _post_repoless(client)

    assert response.status_code == 502


def test_submit_review_404s_for_an_unregistered_repo() -> None:
    app = _build_app(session=FakeAsyncSession(registered_repo=None))
    client = TestClient(app)

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py"]})

    assert response.status_code == 404


def test_get_review_returns_the_job() -> None:
    job = _make_review_job()
    app = _build_app(session=FakeAsyncSession(review_job=job))
    client = TestClient(app)

    response = client.get(f"/api/reviews/{job.review_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["file_paths"] == ["src/module.py"]


def test_get_review_file_content_returns_a_guest_files_stored_source() -> None:
    job = _make_review_job(repo_id=None, requested_by_user_id=None, guest_session_id=7, file_paths=["example.py"])
    guest_file = GuestReviewFile(id=1, review_job_id=job.id, file_path="example.py", content="def f(): ...\n")
    client = TestClient(_build_app(session=FakeAsyncSession(review_job=job, guest_file=guest_file)))

    response = client.get(f"/api/reviews/{job.review_id}/files/content", params={"file_path": "example.py"})

    assert response.json() == {"file_path": "example.py", "content": "def f(): ...\n"}


def test_get_review_file_content_404s_for_a_file_with_no_stored_source() -> None:
    """Verify a repo review (whose source lives in indexed files, not here) gets a clean 404."""
    job = _make_review_job()
    client = TestClient(_build_app(session=FakeAsyncSession(review_job=job)))

    response = client.get(f"/api/reviews/{job.review_id}/files/content", params={"file_path": "src/module.py"})

    assert response.status_code == 404
