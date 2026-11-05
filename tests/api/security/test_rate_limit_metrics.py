"""
    Tests that a request refused by the rate limiter is counted under the scope it was limiting.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.observability.metrics import ApiMetrics
from api.security import rate_limit
from api.security.rate_limit import WINDOW_SECONDS, RateLimiter, RateLimitExceededError
from tests.api.fake_rate_limit import FakeCounterRedis
from tests.api.security.test_rate_limit import FakeClock
from tests.metric_points import GUARD_REFUSALS, point_with, points_for

LIMIT = 3
_GUARD = "code_reviewer.guard"
_SCOPE = "code_reviewer.scope"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_api_metrics: ApiMetrics) -> None:
    """Points the limiter at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(rate_limit, "api_metrics", isolated_api_metrics)


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter(FakeCounterRedis(), FakeClock(now=WINDOW_SECONDS * 1000 + 10))


async def _hit_times(limiter: RateLimiter, times: int, scope: str) -> None:
    for _ in range(times):
        try:
            await limiter.hit(scope, 1, LIMIT)
        except RateLimitExceededError:
            pass


@pytest.mark.asyncio
async def test_requests_within_the_limit_record_no_refusal(
    limiter: RateLimiter, metric_reader: InMemoryMetricReader
) -> None:
    """Verify using the whole budget is not a refusal."""
    await _hit_times(limiter, LIMIT, "review_submission")

    assert points_for(metric_reader, GUARD_REFUSALS) == []


@pytest.mark.asyncio
async def test_the_request_over_the_limit_is_counted_with_its_scope(
    limiter: RateLimiter, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the first request past the budget records one refusal under the scope's name."""
    await _hit_times(limiter, LIMIT + 1, "review_submission")

    point = point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "rate_limit", _SCOPE: "review_submission"})
    assert point.value == 1


@pytest.mark.asyncio
async def test_every_refused_request_is_counted(limiter: RateLimiter, metric_reader: InMemoryMetricReader) -> None:
    """Verify a caller that keeps hitting the limit adds one refusal per request, matching the 429s they see."""
    await _hit_times(limiter, LIMIT + 4, "review_submission")

    assert point_with(metric_reader, GUARD_REFUSALS, {_SCOPE: "review_submission"}).value == 4


@pytest.mark.asyncio
async def test_a_refusal_still_raises_the_error_the_route_turns_into_a_429(limiter: RateLimiter) -> None:
    """Verify recording the refusal does not swallow it."""
    await _hit_times(limiter, LIMIT, "review_submission")

    with pytest.raises(RateLimitExceededError):
        await limiter.hit("review_submission", 1, LIMIT)


@pytest.mark.asyncio
async def test_each_scope_is_counted_on_its_own(limiter: RateLimiter, metric_reader: InMemoryMetricReader) -> None:
    """Verify refusals under two scopes stay in two series."""
    await _hit_times(limiter, LIMIT + 1, "review_submission")
    await _hit_times(limiter, LIMIT + 1, "similar_code_search")

    scopes = {dict(point.attributes)[_SCOPE] for point in points_for(metric_reader, GUARD_REFUSALS)}
    assert scopes == {"review_submission", "similar_code_search"}
