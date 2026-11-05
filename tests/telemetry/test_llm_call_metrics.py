from contextlib import suppress

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.telemetry.metrics import PipelineMetrics
from code_reviewer.telemetry.run_summary import RunSummary, ToolCallRecord
from tests.metric_points import (
    AGENT_MODEL_TURNS,
    AGENT_SKIPPED,
    AGENT_TOOL_CALLS,
    LLM_CALL_DURATION,
    LLM_CALL_ERRORS,
    LLM_CALLS_IN_FLIGHT,
    LLM_TOKENS,
    point_with,
    points_for,
)

MODEL = "deepseek/test-model"


def _classify_as_rate_limit(error: BaseException) -> str:
    """A stand-in classifier, so these tests depend on no provider library."""
    return "rate_limit"


def _summary() -> RunSummary:
    """A run of three model turns that used a tool twice, once unsuccessfully."""
    return RunSummary(
        model_turns=3,
        input_tokens=100,
        output_tokens=40,
        reasoning_tokens=25,
        cached_input_tokens=60,
        tool_calls=[
            ToolCallRecord(name="get_file_chunks", failed=False),
            ToolCallRecord(name="get_file_chunks", failed=True),
        ],
    )


def test_track_llm_call_records_one_duration_per_call(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify each real model call adds one observation to the latency histogram."""
    with isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        pass

    assert point_with(metric_reader, LLM_CALL_DURATION, {"code_reviewer.model": MODEL}).count == 1


def test_track_llm_call_leaves_no_call_in_flight_after_success(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the in-flight gauge returns to zero once the call finishes."""
    with isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        pass

    assert point_with(metric_reader, LLM_CALLS_IN_FLIGHT, {"code_reviewer.code_key": "VAR"}).value == 0


def test_track_llm_call_leaves_no_call_in_flight_after_failure(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a failing call still decrements the gauge, or it would drift upward forever."""
    with suppress(RuntimeError), isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        raise RuntimeError("provider down")

    assert point_with(metric_reader, LLM_CALLS_IN_FLIGHT, {"code_reviewer.code_key": "VAR"}).value == 0


def test_track_llm_call_counts_a_failure_under_the_cause_the_classifier_names(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the error counter carries the cause returned by the injected classifier."""
    with suppress(RuntimeError), isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        raise RuntimeError("provider down")

    assert point_with(metric_reader, LLM_CALL_ERRORS, {"code_reviewer.cause": "rate_limit"}).value == 1


def test_track_llm_call_records_no_error_for_a_successful_call(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a call that succeeds leaves the error counter untouched."""
    with isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        pass

    assert points_for(metric_reader, LLM_CALL_ERRORS) == []


def test_track_llm_call_still_times_a_failed_call(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a failed attempt is part of the latency histogram too, since slow failures are what hurt."""
    with suppress(RuntimeError), isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
        raise RuntimeError("provider down")

    assert point_with(metric_reader, LLM_CALL_DURATION, {"code_reviewer.model": MODEL}).count == 1


def test_track_llm_call_reraises_the_original_exception(isolated_pipeline_metrics: PipelineMetrics) -> None:
    """Verify recording never swallows the failure, because the retry middleware above depends on seeing it."""
    with pytest.raises(RuntimeError, match="provider down"):
        with isolated_pipeline_metrics.track_llm_call("VAR", MODEL, _classify_as_rate_limit):
            raise RuntimeError("provider down")


@pytest.mark.parametrize(
    "token_type,expected",
    [("input", 100), ("output", 40), ("reasoning", 25), ("cached", 60)],
)
def test_record_run_summary_adds_each_token_type_under_its_own_label(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader, token_type: str, expected: int
) -> None:
    """Verify the four token counts land on separate series, so cost can be worked out per type."""
    isolated_pipeline_metrics.record_run_summary("VAR", MODEL, _summary())

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": token_type}).value == expected


def test_record_run_summary_labels_tokens_with_the_model(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify tokens carry the model name, so a fast-tier agent is not mixed up with a main-model one."""
    isolated_pipeline_metrics.record_run_summary("VAR", MODEL, _summary())

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.model": MODEL}).value == 100


def test_record_run_summary_records_the_number_of_model_turns(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the turns histogram receives the run's turn count."""
    isolated_pipeline_metrics.record_run_summary("VAR", MODEL, _summary())

    assert point_with(metric_reader, AGENT_MODEL_TURNS, {"code_reviewer.code_key": "VAR"}).sum == 3


def test_record_run_summary_counts_successful_tool_calls(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a successful tool call is counted with status success."""
    isolated_pipeline_metrics.record_run_summary("ARCH", MODEL, _summary())

    assert point_with(metric_reader, AGENT_TOOL_CALLS, {"code_reviewer.tool_status": "success"}).value == 1


def test_record_run_summary_counts_failed_tool_calls(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a failed tool call is counted with status error, so the tool failure rate can be charted."""
    isolated_pipeline_metrics.record_run_summary("ARCH", MODEL, _summary())

    assert point_with(metric_reader, AGENT_TOOL_CALLS, {"code_reviewer.tool_status": "error"}).value == 1


def test_record_agent_skip_counts_the_skip_under_its_reason(
    isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a skipped agent is counted with the reason it was skipped for."""
    isolated_pipeline_metrics.record_agent_skip("COH", "file_exceeds_hard_limit")

    assert point_with(metric_reader, AGENT_SKIPPED, {"code_reviewer.reason": "file_exceeds_hard_limit"}).value == 1
