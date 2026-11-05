"""
    Tests that the file index consumer times each embedding and names why a file failed. The embedding model is a fake.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.indexing.consumers import repo_file_index_consumer
from api.observability.metrics import ApiMetrics
from code_reviewer.rag.errors import ChunkExplanationError
from code_reviewer.rag.repo_data import RepoData
from tests.api.indexing.test_repo_file_index_consumer import (
    FakeConsumerRecord,
    FakeKafkaConsumer,
    _make_consumer,
    _make_message,
)
from tests.metric_points import INDEX_FILE_DURATION, INDEX_FILE_FAILURES, point_with, points_for

_RESULT = "code_reviewer.result"
_CAUSE = "code_reviewer.cause"


class _RaisingRagManager:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        raise self._error


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the consumer at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(repo_file_index_consumer, "api_metrics", isolated_api_metrics)


async def _process(rag_manager: object | None = None) -> None:
    indexed_file = IndexedFile(repo_id=10, file_path="main.py", status=IndexedFileStatus.PENDING)
    consumer, *_ = _make_consumer(indexed_files=[indexed_file], rag_manager=rag_manager)
    record = FakeConsumerRecord(value=_make_message().model_dump_json().encode())
    await consumer._process_message(record, FakeKafkaConsumer([]))


@pytest.mark.asyncio
async def test_an_indexed_file_is_timed_and_records_no_failure(metric_reader: InMemoryMetricReader) -> None:
    """Verify a successful embedding adds one duration point labelled indexed and no failure."""
    await _process()

    assert point_with(metric_reader, INDEX_FILE_DURATION, {_RESULT: "indexed"}).count == 1
    assert points_for(metric_reader, INDEX_FILE_FAILURES) == []


@pytest.mark.asyncio
async def test_a_failed_embedding_is_timed_and_its_cause_is_named(metric_reader: InMemoryMetricReader) -> None:
    """Verify a failing embedding is timed as failed and counted under the cause the classifier names."""
    await _process(_RaisingRagManager(RuntimeError("boom")))

    assert point_with(metric_reader, INDEX_FILE_DURATION, {_RESULT: "failed"}).count == 1
    assert point_with(metric_reader, INDEX_FILE_FAILURES, {_CAUSE: "other"}).value == 1


@pytest.mark.asyncio
async def test_a_chunk_explanation_timeout_is_counted_under_its_own_cause(
    metric_reader: InMemoryMetricReader,
) -> None:
    """Verify the explain-call timeout shows up as its own failure cause in the metric."""
    error = ChunkExplanationError("explain failed")
    error.__cause__ = TimeoutError("hard timeout")

    await _process(_RaisingRagManager(error))

    assert point_with(metric_reader, INDEX_FILE_FAILURES, {_CAUSE: "chunk_explain_timeout"}).value == 1
