"""
    Tests that ApiMetrics turns each cost-guard event into the right instrument and labels.
"""
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from api.observability.metrics import ApiMetrics, CapGuard
from tests.metric_points import GUARD_REFUSALS, GUARD_UNFINISHED_INDEXINGS, GUARD_UNFINISHED_REVIEWS, point_with, points_for

_GUARD = "code_reviewer.guard"
_SCOPE = "code_reviewer.scope"


def test_a_rate_limit_refusal_is_counted_with_its_scope(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a rate-limit refusal carries the route group it protects."""
    isolated_api_metrics.record_rate_limit_refusal("review_submission")

    assert point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "rate_limit", _SCOPE: "review_submission"}).value == 1


def test_rate_limit_scopes_are_kept_apart(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify two scopes are two series, so a dashboard can say which route group is being limited."""
    isolated_api_metrics.record_rate_limit_refusal("review_submission")
    isolated_api_metrics.record_rate_limit_refusal("similar_code_search")

    assert len(points_for(metric_reader, GUARD_REFUSALS)) == 2


def test_a_cap_refusal_is_counted_under_its_guard_with_no_scope(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a cap refusal is labelled by guard alone."""
    isolated_api_metrics.record_cap_refusal(CapGuard.UNFINISHED_REVIEWS)

    point = point_with(metric_reader, GUARD_REFUSALS, {_GUARD: "unfinished_reviews"})
    assert (point.value, _SCOPE in dict(point.attributes)) == (1, False)


def test_each_cap_guard_has_its_own_series(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the three cap guards are distinguishable, since a busy slot lock is not the same as a full cap."""
    for guard in CapGuard:
        isolated_api_metrics.record_cap_refusal(guard)

    guards = {dict(point.attributes)[_GUARD] for point in points_for(metric_reader, GUARD_REFUSALS)}
    assert guards == {"unfinished_reviews", "unfinished_indexings", "review_slot_busy"}


def test_the_unfinished_review_count_is_recorded_as_a_distribution(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify every check adds one observation, so the spread of how close users get to the cap is visible."""
    isolated_api_metrics.record_unfinished_reviews(0)
    isolated_api_metrics.record_unfinished_reviews(3)

    point = points_for(metric_reader, GUARD_UNFINISHED_REVIEWS)[0]
    assert (point.count, point.sum) == (2, 3)


def test_the_unfinished_indexing_count_is_recorded_as_a_distribution(
    isolated_api_metrics: ApiMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the indexing cap has its own histogram, separate from the review one."""
    isolated_api_metrics.record_unfinished_indexings(2)

    assert points_for(metric_reader, GUARD_UNFINISHED_REVIEWS) == []
    assert points_for(metric_reader, GUARD_UNFINISHED_INDEXINGS)[0].sum == 2
