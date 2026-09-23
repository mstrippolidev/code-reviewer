"""
    Tests for the /api/repos/{repo_id}/review and /api/reviews routes against fakes:
    no real DB, no real Kafka.
"""
import uuid
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session, get_kafka_producer
from api.routers.reviews import router as reviews_router
from api.schemas.reviews import ReviewRequestedMessage


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
    ) -> None:
        self.registered_repo = registered_repo
        self.indexed_files = indexed_files or []
        self.review_job = review_job
        self.added: list[object] = []

    async def scalar(self, statement) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is ReviewJob:
            return self.review_job
        return self.registered_repo

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult([file.file_path for file in self.indexed_files])

    def add(self, row: object) -> None:
        self.added.append(row)

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


def test_submit_review_rejects_files_that_are_not_indexed() -> None:
    repo = _make_registered_repo()
    files = [_make_indexed_file(file_path="a.py")]
    app = _build_app(session=FakeAsyncSession(registered_repo=repo, indexed_files=files))
    client = TestClient(app)

    response = client.post("/api/repos/10/review", json={"file_paths": ["a.py", "missing.py"]})

    assert response.status_code == 400


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


def test_get_review_404s_for_an_unknown_review_id() -> None:
    app = _build_app(session=FakeAsyncSession(review_job=None))
    client = TestClient(app)

    response = client.get(f"/api/reviews/{uuid.uuid4()}")

    assert response.status_code == 404
