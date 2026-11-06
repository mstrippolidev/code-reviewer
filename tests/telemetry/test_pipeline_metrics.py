from contextlib import suppress

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.telemetry.metrics import (
    LLM_LATENCY_BUCKETS_SECONDS,
    REVIEW_COST_BUCKETS_USD,
    PipelineMetrics,
    pipeline_metrics as default_pipeline_metrics,
)
from tests.metric_points import (
    AGENT_INCIDENT_OVERLAPS,
    AGENT_RUN_DURATION,
    FILE_SKIPPED,
    INTAKE_REJECTIONS,
    REVIEW_COST,
    point_with,
    points_for,
)


def test_track_agent_run_without_an_sdk_configured_does_not_raise() -> None:
    """Verify the default instance is a no-op when no SDK is installed.

    code_reviewer imports the API only, so tests and any host without telemetry must pay nothing.
    """
    with default_pipeline_metrics.track_agent_run("VAR"):
        pass


def test_track_agent_run_records_one_data_point_per_run(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a finished run adds exactly one observation to the histogram."""
    with isolated_pipeline_metrics.track_agent_run("VAR"):
        pass

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.code_key": "VAR"}).count == 1


def test_track_agent_run_labels_a_finished_run_as_completed(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the outcome label is completed when the enclosed block returns normally."""
    with isolated_pipeline_metrics.track_agent_run("VAR"):
        pass

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "completed"}).count == 1


def test_track_agent_run_labels_the_point_with_the_agent_code_key(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the code_key label carries the agent that ran, so dashboards can split by agent."""
    with isolated_pipeline_metrics.track_agent_run("TCASE"):
        pass

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.code_key": "TCASE"}).count == 1


def test_track_agent_run_labels_a_raising_run_as_failed(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify an exception inside the block is recorded as a failed run."""
    with suppress(RuntimeError), isolated_pipeline_metrics.track_agent_run("VAR"):
        raise RuntimeError("model unreachable")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "failed"}).count == 1


def test_track_agent_run_labels_a_timeout_as_timed_out(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a TimeoutError is told apart from other failures, since it points at a slow model, not a broken one."""
    with suppress(TimeoutError), isolated_pipeline_metrics.track_agent_run("VAR"):
        raise TimeoutError("LLM call exceeded the hard timeout")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "timed_out"}).count == 1


def test_track_agent_run_labels_a_wrapped_timeout_as_timed_out(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a timeout is still recognised when the agent re-raises it wrapped in another exception.

    AgentBase wraps every failure in AgentInvocationError with the original as the cause.
    """
    with suppress(RuntimeError), isolated_pipeline_metrics.track_agent_run("VAR"):
        raise RuntimeError("agent failed") from TimeoutError("hard timeout")

    assert point_with(metric_reader, AGENT_RUN_DURATION, {"code_reviewer.outcome": "timed_out"}).count == 1


def test_track_agent_run_does_not_label_an_unrelated_failure_as_timed_out(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify only timeouts get the timed_out outcome, so the failed count stays meaningful."""
    with suppress(RuntimeError), isolated_pipeline_metrics.track_agent_run("VAR"):
        raise RuntimeError("agent failed") from ValueError("bad output")

    assert points_for(metric_reader, AGENT_RUN_DURATION)[0].attributes["code_reviewer.outcome"] == "failed"


def test_track_agent_run_reraises_the_original_exception(isolated_pipeline_metrics: PipelineMetrics) -> None:
    """Verify recording never swallows the failure, since the pipeline relies on seeing it."""
    with pytest.raises(RuntimeError, match="model unreachable"):
        with isolated_pipeline_metrics.track_agent_run("VAR"):
            raise RuntimeError("model unreachable")


def test_agent_run_duration_uses_second_scale_buckets(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the SDK honours the bucket advisory.

    The spec lets an implementation ignore it, and the default millisecond buckets would put every LLM call in the last one.
    """
    with isolated_pipeline_metrics.track_agent_run("VAR"):
        pass

    assert tuple(points_for(metric_reader, AGENT_RUN_DURATION)[0].explicit_bounds) == tuple(
        LLM_LATENCY_BUCKETS_SECONDS
    )


def test_record_file_skipped_counts_each_reason_on_its_own_series(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify two reasons do not share a series and a repeated reason adds up."""
    isolated_pipeline_metrics.record_file_skipped("intake_rejected")
    isolated_pipeline_metrics.record_file_skipped("intake_rejected")
    isolated_pipeline_metrics.record_file_skipped("file_too_large")

    assert point_with(metric_reader, FILE_SKIPPED, {"code_reviewer.reason": "intake_rejected"}).value == 2
    assert point_with(metric_reader, FILE_SKIPPED, {"code_reviewer.reason": "file_too_large"}).value == 1


def test_record_intake_rejection_counts_under_the_validator(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the rejection is labelled with the validator, and nothing else."""
    isolated_pipeline_metrics.record_intake_rejection("prompt_injection")

    point = point_with(metric_reader, INTAKE_REJECTIONS, {"code_reviewer.validator": "prompt_injection"})
    assert (point.value, dict(point.attributes)) == (1, {"code_reviewer.validator": "prompt_injection"})


def test_record_incident_overlaps_counts_one_per_pair(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify each pair given is one count under its own name."""
    isolated_pipeline_metrics.record_incident_overlaps(["SOLID2+TEST", "SOLID2+TEST", "COH+COUP"])

    assert point_with(metric_reader, AGENT_INCIDENT_OVERLAPS, {"code_reviewer.agent_pair": "SOLID2+TEST"}).value == 2
    assert point_with(metric_reader, AGENT_INCIDENT_OVERLAPS, {"code_reviewer.agent_pair": "COH+COUP"}).value == 1


def test_record_review_cost_adds_one_observation_with_the_cost_buckets(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify one finished review is one point, bucketed in dollars rather than the default millisecond buckets."""
    isolated_pipeline_metrics.record_review_cost(1.5)

    point = points_for(metric_reader, REVIEW_COST)[0]
    assert (point.count, point.sum, tuple(point.explicit_bounds)) == (1, 1.5, tuple(REVIEW_COST_BUCKETS_USD))


def test_five_dollars_is_a_review_cost_bucket_boundary() -> None:
    """Verify the expensive-review alert can read "above $5" from the le="5" bucket exactly."""
    assert 5 in REVIEW_COST_BUCKETS_USD


def test_record_incident_overlaps_with_no_pairs_records_nothing(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a file with no overlap leaves the counter empty rather than adding zeros."""
    isolated_pipeline_metrics.record_incident_overlaps([])

    assert points_for(metric_reader, AGENT_INCIDENT_OVERLAPS) == []
