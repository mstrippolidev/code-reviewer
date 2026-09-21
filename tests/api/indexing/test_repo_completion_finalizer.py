"""
    Tests for RepoCompletionFinalizer against fakes: no real DB, no real Kafka.
"""
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy import Update

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from api.indexing.topics import REPO_STATUS_PROGRESS
from api.schemas.repos import RepoStatusProgressMessage


@dataclass
class _UpdateResult:
    rowcount: int


class _CountResult:
    def __init__(self, status_counts: dict[IndexedFileStatus, int]) -> None:
        self._rows = list(status_counts.items())

    def all(self) -> list[tuple[IndexedFileStatus, int]]:
        return self._rows


class FakeAsyncSession:
    """Seeded with one RegisteredRepo and per-status file counts. Applies the finalizer's
    conditional UPDATE against the seeded repo for real, so the WHERE-status guard is exercised
    rather than assumed."""

    def __init__(self, *, registered_repo: RegisteredRepo | None, status_counts: dict[IndexedFileStatus, int]) -> None:
        self.registered_repo = registered_repo
        self._status_counts = status_counts
        self.commit_count = 0

    async def scalar(self, _statement) -> RegisteredRepo | None:
        return self.registered_repo

    async def execute(self, statement) -> _UpdateResult | _CountResult:
        if isinstance(statement, Update):
            return self._apply_update(statement)
        return _CountResult(self._status_counts)

    def _apply_update(self, statement: Update) -> _UpdateResult:
        if self.registered_repo.status != RepoIndexStatus.INDEXING:
            return _UpdateResult(rowcount=0)
        params = statement.compile().params
        self.registered_repo.status = params["status"]
        self.registered_repo.status_reason = params["status_reason"]
        return _UpdateResult(rowcount=1)

    async def commit(self) -> None:
        self.commit_count += 1


class FakeRepoProducer:
    def __init__(self, *, publish_error: Exception | None = None) -> None:
        self._publish_error = publish_error
        self.published: list[tuple[str, RepoStatusProgressMessage, bytes]] = []

    async def publish(self, topic: str, message: RepoStatusProgressMessage, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))

    @property
    def status_messages(self) -> list[RepoStatusProgressMessage]:
        return [message for topic, message, _ in self.published if topic == REPO_STATUS_PROGRESS]


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.INDEXING,
        "total_files_expected": 10,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


def _zero_counts() -> dict[IndexedFileStatus, int]:
    return {status: 0 for status in IndexedFileStatus}


@pytest.mark.asyncio
async def test_marks_the_repo_completed_when_every_file_indexed_successfully() -> None:
    repo = _make_registered_repo(total_files_expected=3)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 3}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.COMPLETED
    assert repo.status_reason is None


@pytest.mark.asyncio
async def test_marks_the_repo_completed_when_only_some_files_failed() -> None:
    """Per the product rule: 47 indexed out of 50 is a completed run, not a failed one."""
    repo = _make_registered_repo(total_files_expected=50)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 47, IndexedFileStatus.FAILED: 3}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.COMPLETED


@pytest.mark.asyncio
async def test_marks_the_repo_completed_when_every_file_was_skipped() -> None:
    repo = _make_registered_repo(total_files_expected=2)
    counts = _zero_counts() | {IndexedFileStatus.SKIPPED: 2}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.COMPLETED


@pytest.mark.asyncio
async def test_marks_the_repo_failed_when_no_file_could_be_indexed() -> None:
    repo = _make_registered_repo(total_files_expected=3)
    counts = _zero_counts() | {IndexedFileStatus.FAILED: 3}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.FAILED
    assert "3" in repo.status_reason


@pytest.mark.asyncio
async def test_does_not_finalize_before_every_expected_file_reaches_a_terminal_status() -> None:
    repo = _make_registered_repo(total_files_expected=5)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 4}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.INDEXING
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_does_nothing_when_total_files_expected_is_not_set_yet() -> None:
    repo = _make_registered_repo(total_files_expected=None)
    session = FakeAsyncSession(registered_repo=repo, status_counts=_zero_counts())
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.INDEXING


@pytest.mark.asyncio
async def test_does_not_finalize_a_paused_repo_even_if_dispatched_files_are_all_terminal() -> None:
    """A paused repo's total_files_expected still counts every walked file, but only the
    already-dispatched ones ever get a row -- so this state only arises via a WHERE-status
    race, and the guard must hold regardless."""
    repo = _make_registered_repo(status=RepoIndexStatus.PAUSED, total_files_expected=5)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 5}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.PAUSED


@pytest.mark.asyncio
async def test_publishes_the_final_status_including_total_files_expected() -> None:
    repo = _make_registered_repo(total_files_expected=3)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 3}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    producer = FakeRepoProducer()
    finalizer = RepoCompletionFinalizer(producer)

    await finalizer.finalize_if_complete(10, session)

    [message] = producer.status_messages
    assert message.status == RepoIndexStatus.COMPLETED
    assert message.total_files_expected == 3


@pytest.mark.asyncio
async def test_swallows_a_status_progress_publish_failure() -> None:
    repo = _make_registered_repo(total_files_expected=3)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 3}
    session = FakeAsyncSession(registered_repo=repo, status_counts=counts)
    producer = FakeRepoProducer(publish_error=RuntimeError("broker unreachable"))
    finalizer = RepoCompletionFinalizer(producer)

    await finalizer.finalize_if_complete(10, session)

    assert repo.status == RepoIndexStatus.COMPLETED


@pytest.mark.asyncio
async def test_does_nothing_when_the_registered_repo_row_is_missing() -> None:
    session = FakeAsyncSession(registered_repo=None, status_counts=_zero_counts())
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())

    await finalizer.finalize_if_complete(10, session)

    assert session.commit_count == 0
