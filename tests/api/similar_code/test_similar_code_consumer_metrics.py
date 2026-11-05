"""
    Tests that the similar-code consumer reports its lifecycle to the metrics hook: queue wait when a worker
    starts a search, how long the check took, and the final status. The check itself is replaced by a fake.
"""
from datetime import UTC, datetime, timedelta

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.db.models.registered_repo import RegisteredRepo
from api.db.models.similar_code_search import SimilarCodeSearch, SimilarCodeSearchStatus
from api.observability.metrics import ApiMetrics
from api.similar_code import similar_code_consumer
from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.rag.errors import VectorStoreQueryError
from tests.api.similar_code.test_similar_code_consumer import (
    MESSAGE,
    FakeConsumerRecord,
    FakeDatabaseEngine,
    FakeSession,
    FakeSnippetCheck,
    _install_check,
    _make_consumer,
    _make_repo,
    _make_search,
)
from tests.metric_points import SEARCH_DURATION, SEARCH_FINISHED, SEARCH_QUEUE_WAIT, point_with, points_for

_RESULT = "code_reviewer.result"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the consumer at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(similar_code_consumer, "api_metrics", isolated_api_metrics)


async def _handle(search: SimilarCodeSearch, repo: RegisteredRepo | None) -> None:
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=search, repo=repo)))
    await consumer._handle_parsed_message(MESSAGE, FakeConsumerRecord(), None)


async def _handle_with_repo(search: SimilarCodeSearch) -> None:
    await _handle(search, _make_repo())


@pytest.mark.asyncio
async def test_queue_wait_is_the_time_since_the_search_was_created(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the wait recorded when a worker starts a search is measured from its creation."""
    _install_check(monkeypatch, FakeSnippetCheck())
    search = _make_search(created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=30))

    await _handle_with_repo(search)

    assert 30 <= points_for(metric_reader, SEARCH_QUEUE_WAIT)[0].sum < 60


@pytest.mark.asyncio
async def test_a_completed_search_is_timed_and_counted(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a search that finds its answer adds one timed check and one final status, both completed."""
    _install_check(monkeypatch, FakeSnippetCheck())

    await _handle_with_repo(_make_search())

    assert point_with(metric_reader, SEARCH_DURATION, {_RESULT: "completed"}).count == 1
    assert point_with(metric_reader, SEARCH_FINISHED, {_RESULT: "completed"}).value == 1


@pytest.mark.asyncio
async def test_a_refused_snippet_is_counted_as_rejected(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a refused snippet is its own result, not mixed into failures."""
    _install_check(monkeypatch, FakeSnippetCheck(error=IntakeRejectedError("injection")))

    await _handle_with_repo(_make_search())

    assert point_with(metric_reader, SEARCH_FINISHED, {_RESULT: "rejected"}).value == 1
    assert point_with(metric_reader, SEARCH_DURATION, {_RESULT: "rejected"}).count == 1


@pytest.mark.asyncio
async def test_an_infrastructure_failure_is_counted_as_failed(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify an outage during the check counts as a failed search."""
    _install_check(monkeypatch, FakeSnippetCheck(error=VectorStoreQueryError("down")))

    await _handle_with_repo(_make_search())

    assert point_with(metric_reader, SEARCH_FINISHED, {_RESULT: "failed"}).value == 1


@pytest.mark.asyncio
async def test_a_crash_before_the_check_is_counted_once_as_failed_and_not_timed(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the recovery path counts the search as failed exactly once, with no duration for a check that never ran."""
    _install_check(monkeypatch, FakeSnippetCheck())

    await _handle(_make_search(), None)

    assert point_with(metric_reader, SEARCH_FINISHED, {_RESULT: "failed"}).value == 1
    assert points_for(metric_reader, SEARCH_DURATION) == []


@pytest.mark.asyncio
async def test_a_search_that_already_finished_records_nothing(
    monkeypatch: pytest.MonkeyPatch, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a redelivered message for a finished search adds no queue wait and no status."""
    _install_check(monkeypatch, FakeSnippetCheck())

    await _handle_with_repo(_make_search(status=SimilarCodeSearchStatus.COMPLETED))

    assert points_for(metric_reader, SEARCH_QUEUE_WAIT) == []
    assert points_for(metric_reader, SEARCH_FINISHED) == []
