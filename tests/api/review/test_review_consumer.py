"""
    Tests for ReviewRequestConsumer against fakes: no real DB, no real Kafka, no real pipeline.
    run_pipeline is monkeypatched out (already covered end to end in
    tests/pipeline/test_orchestrator.py) so these exercise the consumer's own
    DB/broadcast wiring only.
"""
import uuid
from datetime import datetime

import pytest

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.review import review_consumer
from api.review.review_consumer import ReviewRequestConsumer, ReviewRequestConsumerDependencies
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster
from api.schemas.reviews import ReviewAgentProgressMessage, ReviewFileProgressMessage, ReviewRequestedMessage
from code_reviewer.schemas.review import AgentReviewEntry, AggregatorOutput, CodeKey, Meta, PrRecommendation


class _ScalarsResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


class FakeAsyncSession:
    """Blind to query shape, like this project's other consumer/router fakes: seeded per test."""

    def __init__(
        self,
        *,
        registered_repo: RegisteredRepo | None = None,
        review_job: ReviewJob | None = None,
        indexed_files: list[IndexedFile] | None = None,
    ) -> None:
        self.registered_repo = registered_repo
        self.review_job = review_job
        self.indexed_files = indexed_files or []
        self.commit_count = 0

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def scalar(self, statement) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is ReviewJob:
            return self.review_job
        return self.registered_repo

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult(self.indexed_files)

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabaseEngine:
    def __init__(self, session: FakeAsyncSession) -> None:
        self._session = session

    def new_session(self) -> FakeAsyncSession:
        return self._session


class FakeBroadcaster(ReviewProgressBroadcaster):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[object] = []

    async def publish(self, review_id, event) -> None:
        self.published.append(event)


def _make_message(**overrides) -> ReviewRequestedMessage:
    defaults = {
        "review_id": uuid.uuid4(),
        "repo_id": 10,
        "owner_id": 99,
        "requested_by_user_id": 1,
        "file_paths": ["a.py"],
    }
    defaults.update(overrides)
    return ReviewRequestedMessage(**defaults)


def _make_job(review_msg: ReviewRequestedMessage) -> ReviewJob:
    return ReviewJob(
        id=1,
        review_id=review_msg.review_id,
        repo_id=review_msg.repo_id,
        requested_by_user_id=review_msg.requested_by_user_id,
        file_paths=review_msg.file_paths,
        status=ReviewJobStatus.PENDING,
        status_reason=None,
        result=None,
        created_at=datetime(2026, 1, 1),
        completed_at=None,
    )


def _make_repo() -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        branch="main",
        commit_sha="abc123",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
        created_at=datetime(2026, 1, 1),
    )


def _make_result() -> AggregatorOutput:
    return AggregatorOutput(
        meta=Meta(
            total_files_in_pr=1,
            total_files_reviewed=1,
            overall_rating=90.0,
            critical_incidents=0,
            high_incidents=0,
            medium_incidents=0,
            low_incidents=0,
            agents_run=[],
            pr_recommendation=PrRecommendation.APPROVED,
            rejection_reason=None,
            skipped_files=[],
        ),
        review=[],
    )


def _make_consumer(*, session: FakeAsyncSession, broadcaster: FakeBroadcaster) -> ReviewRequestConsumer:
    dependencies = ReviewRequestConsumerDependencies(
        database_engine=FakeDatabaseEngine(session), agents_container=None, broadcaster=broadcaster
    )
    return ReviewRequestConsumer(dependencies)


@pytest.mark.asyncio
async def test_run_review_completes_and_stores_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    review_msg = _make_message()
    job = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")],
    )
    broadcaster = FakeBroadcaster()
    consumer = _make_consumer(session=session, broadcaster=broadcaster)

    async def fake_run_pipeline(*args, **kwargs) -> AggregatorOutput:
        return _make_result()

    monkeypatch.setattr(review_consumer, "run_pipeline", fake_run_pipeline)

    await consumer._run_review(review_msg)

    assert job.status == ReviewJobStatus.COMPLETED
    assert job.result["meta"]["overall_rating"] == 90.0
    assert job.completed_at is not None
    assert [event.status for event in broadcaster.published] == [ReviewJobStatus.RUNNING, ReviewJobStatus.COMPLETED]


@pytest.mark.asyncio
async def test_execute_pipeline_publishes_agent_progress_events(monkeypatch: pytest.MonkeyPatch) -> None:
    review_msg = _make_message()
    job = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")],
    )
    broadcaster = FakeBroadcaster()
    consumer = _make_consumer(session=session, broadcaster=broadcaster)
    entry = AgentReviewEntry(file_path="a.py", code_key=CodeKey.VAR, incidents=[], rating=100)

    async def fake_run_pipeline(*args, on_agent_reviewed=None, **kwargs) -> AggregatorOutput:
        if on_agent_reviewed is not None:
            await on_agent_reviewed(CodeKey.VAR, entry)
        return _make_result()

    monkeypatch.setattr(review_consumer, "run_pipeline", fake_run_pipeline)

    await consumer._run_review(review_msg)

    agent_events = [event for event in broadcaster.published if isinstance(event, ReviewAgentProgressMessage)]
    assert len(agent_events) == 1
    assert agent_events[0].code_key == CodeKey.VAR
    assert agent_events[0].file_path == "a.py"


@pytest.mark.asyncio
async def test_execute_pipeline_publishes_a_failed_file_progress_event(monkeypatch: pytest.MonkeyPatch) -> None:
    review_msg = _make_message()
    job = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")],
    )
    broadcaster = FakeBroadcaster()
    consumer = _make_consumer(session=session, broadcaster=broadcaster)

    async def fake_run_pipeline(*args, on_file_reviewed=None, **kwargs) -> AggregatorOutput:
        if on_file_reviewed is not None:
            await on_file_reviewed("a.py", True, [])
        return _make_result()

    monkeypatch.setattr(review_consumer, "run_pipeline", fake_run_pipeline)

    await consumer._run_review(review_msg)

    file_events = [event for event in broadcaster.published if isinstance(event, ReviewFileProgressMessage)]
    assert len(file_events) == 1
    assert file_events[0].file_path == "a.py"
    assert file_events[0].failed is True
    assert job.agent_entries is None


@pytest.mark.asyncio
async def test_execute_pipeline_persists_agent_entries_per_file(monkeypatch: pytest.MonkeyPatch) -> None:
    review_msg = _make_message(file_paths=["a.py", "b.py"])
    job = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[
            IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n"),
            IndexedFile(id=2, repo_id=10, file_path="b.py", status=IndexedFileStatus.INDEXED, content="y = 2\n"),
        ],
    )
    broadcaster = FakeBroadcaster()
    consumer = _make_consumer(session=session, broadcaster=broadcaster)
    entry_a = AgentReviewEntry(file_path="a.py", code_key=CodeKey.VAR, incidents=[], rating=100)
    entry_b = AgentReviewEntry(file_path="b.py", code_key=CodeKey.ERR, incidents=[], rating=80)

    async def fake_run_pipeline(*args, on_file_reviewed=None, **kwargs) -> AggregatorOutput:
        if on_file_reviewed is not None:
            await on_file_reviewed("a.py", False, [entry_a])
            await on_file_reviewed("b.py", False, [entry_b])
        return _make_result()

    monkeypatch.setattr(review_consumer, "run_pipeline", fake_run_pipeline)

    await consumer._run_review(review_msg)

    assert job.agent_entries["a.py"]["VAR"]["rating"] == 100
    assert job.agent_entries["b.py"]["ERR"]["rating"] == 80
    assert job.agent_entries["a.py"].keys() == {"VAR"}, "b.py's entries must not leak into a.py's"


@pytest.mark.asyncio
async def test_handle_parsed_message_marks_the_job_failed_when_a_file_is_missing() -> None:
    review_msg = _make_message(file_paths=["a.py", "missing.py"])
    job = _make_job(review_msg)
    session = FakeAsyncSession(
        registered_repo=_make_repo(),
        review_job=job,
        indexed_files=[IndexedFile(id=1, repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="x = 1\n")],
    )
    broadcaster = FakeBroadcaster()
    consumer = _make_consumer(session=session, broadcaster=broadcaster)

    await consumer._handle_parsed_message(review_msg, msg=None, consumer=None)

    assert job.status == ReviewJobStatus.FAILED
    assert job.status_reason == review_consumer._GENERIC_FAILURE_REASON
    assert broadcaster.published[-1].status == ReviewJobStatus.FAILED
