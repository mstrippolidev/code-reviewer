"""
    Tests that a repo reaching a final indexing status is counted once, with the files it ended with.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RepoIndexStatus
from api.indexing import repo_completion_finalizer, repo_indexer
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from api.indexing.repo_indexer import RepoIndexer
from api.observability.metrics import ApiMetrics
from tests.api.indexing.test_repo_completion_finalizer import (
    FakeAsyncSession,
    FakeRepoProducer,
    _make_registered_repo,
    _zero_counts,
)
from tests.metric_points import INDEX_FILES, INDEX_REPO_FINISHED, point_with, points_for

_RESULT = "code_reviewer.result"
_FILE_STATUS = "code_reviewer.file_status"


class _RepoSession:
    def __init__(self, repo) -> None:
        self.repo = repo

    async def scalar(self, _statement):
        return self.repo

    async def commit(self) -> None:
        return None


class _NoopFinalizer:
    async def fail_pull_request_reviews(self, repo_id: int, session: object) -> None:
        return None


class _IndexerDependencies:
    repo_producer = FakeRepoProducer()
    completion_finalizer = _NoopFinalizer()


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points both recorders at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(repo_completion_finalizer, "api_metrics", isolated_api_metrics)
    monkeypatch.setattr(repo_indexer, "api_metrics", isolated_api_metrics)


async def _finalize(repo, counts: dict[IndexedFileStatus, int]) -> None:
    finalizer = RepoCompletionFinalizer(FakeRepoProducer())
    await finalizer.finalize_if_complete(10, FakeAsyncSession(registered_repo=repo, status_counts=counts))


@pytest.mark.asyncio
async def test_a_completed_repo_is_counted_with_its_files_by_status(metric_reader: InMemoryMetricReader) -> None:
    """Verify a repo that finishes with some failed files counts as completed and reports each file status."""
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 47, IndexedFileStatus.SKIPPED: 1, IndexedFileStatus.FAILED: 2}

    await _finalize(_make_registered_repo(total_files_expected=50), counts)

    assert point_with(metric_reader, INDEX_REPO_FINISHED, {_RESULT: "completed"}).value == 1
    assert point_with(metric_reader, INDEX_FILES, {_FILE_STATUS: "indexed"}).value == 47
    assert point_with(metric_reader, INDEX_FILES, {_FILE_STATUS: "skipped"}).value == 1
    assert point_with(metric_reader, INDEX_FILES, {_FILE_STATUS: "failed"}).value == 2


@pytest.mark.asyncio
async def test_a_repo_whose_files_all_failed_is_counted_as_failed(metric_reader: InMemoryMetricReader) -> None:
    """Verify the final status in the metric is the one the finalizer resolved, not a separate rule."""
    counts = _zero_counts() | {IndexedFileStatus.FAILED: 3}

    await _finalize(_make_registered_repo(total_files_expected=3), counts)

    assert point_with(metric_reader, INDEX_REPO_FINISHED, {_RESULT: "failed"}).value == 1


@pytest.mark.asyncio
async def test_a_repo_still_waiting_on_files_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify nothing is counted until every expected file has reached a terminal status."""
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 4}

    await _finalize(_make_registered_repo(total_files_expected=5), counts)

    assert points_for(metric_reader, INDEX_REPO_FINISHED) == []


@pytest.mark.asyncio
async def test_a_repo_another_caller_already_finalized_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify losing the race to finalize adds no second count for the same repo."""
    repo = _make_registered_repo(status=RepoIndexStatus.COMPLETED, total_files_expected=3)
    counts = _zero_counts() | {IndexedFileStatus.INDEXED: 3}

    await _finalize(repo, counts)

    assert points_for(metric_reader, INDEX_REPO_FINISHED) == []


@pytest.mark.asyncio
async def test_a_repo_that_fails_before_any_file_is_processed_is_counted_as_failed(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify a failed walk or fetch is counted, with no file counts, since it never reaches the finalizer."""
    indexer = RepoIndexer(_IndexerDependencies())

    await indexer._mark_repo_failed(10, "tarball download failed", _RepoSession(_make_registered_repo()))

    assert point_with(metric_reader, INDEX_REPO_FINISHED, {_RESULT: "failed"}).value == 1
    assert point_with(metric_reader, INDEX_FILES, {_FILE_STATUS: "indexed"}).value == 0
