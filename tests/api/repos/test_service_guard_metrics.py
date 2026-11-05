"""
    Tests that the repo lifecycle service reports how close a user is to the indexing cap and every refusal.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.db.models.registered_repo import RepoIndexStatus
from api.observability.metrics import ApiMetrics
from api.repos import service as service_module
from api.repos.errors import TooManyIndexJobsError
from tests.api.repos.test_service import (
    MAX_UNFINISHED_INDEXINGS,
    REQUEST,
    FakeRepoStore,
    _build_service,
    _make_registered_repo,
    _make_user,
)
from tests.metric_points import GUARD_REFUSALS, GUARD_UNFINISHED_INDEXINGS, point_with, points_for

_GUARD = "code_reviewer.guard"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the service at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(service_module, "api_metrics", isolated_api_metrics)


def _paused_repo():
    return _make_registered_repo(status=RepoIndexStatus.PAUSED)


@pytest.mark.asyncio
async def test_starting_indexing_records_how_many_the_user_had_unfinished(metric_reader: InMemoryMetricReader) -> None:
    """Verify the cap check reports its count, so the spread of how close users get is visible."""
    service = _build_service(store=FakeRepoStore([], unfinished_indexings=2))

    await service.resume(_paused_repo(), _make_user())

    assert points_for(metric_reader, GUARD_UNFINISHED_INDEXINGS)[0].sum == 2
    assert points_for(metric_reader, GUARD_REFUSALS) == []


@pytest.mark.asyncio
async def test_a_user_at_the_cap_is_counted_as_refused_and_still_raises(metric_reader: InMemoryMetricReader) -> None:
    """Verify the refusal is counted under its guard, and the error the route turns into a 429 still propagates."""
    service = _build_service(store=FakeRepoStore([], unfinished_indexings=MAX_UNFINISHED_INDEXINGS))

    with pytest.raises(TooManyIndexJobsError):
        await service.resume(_paused_repo(), _make_user())

    assert point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "unfinished_indexings"}).value == 1


@pytest.mark.asyncio
async def test_linking_a_second_user_checks_no_cap_and_records_nothing(metric_reader: InMemoryMetricReader) -> None:
    """Verify adding a link starts no indexing, so it neither checks nor reports the cap."""
    healthy = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    service = _build_service(store=FakeRepoStore([], registered=healthy, unfinished_indexings=MAX_UNFINISHED_INDEXINGS))

    await service.register(REQUEST, _make_user(user_id=2))

    assert points_for(metric_reader, GUARD_UNFINISHED_INDEXINGS) == []
    assert points_for(metric_reader, GUARD_REFUSALS) == []
