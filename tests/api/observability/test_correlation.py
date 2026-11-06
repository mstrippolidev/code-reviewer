"""
    Tests that the correlation filter stamps the trace id and the business ids on log records.
"""
import asyncio
import logging
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider

from api.observability.correlation import CorrelationFilter, CorrelationIds, correlation_scope

REVIEW_ID = UUID("0af76519-16cd-43dd-8448-eb211c80319c")


def _stamped_record() -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
    CorrelationFilter().filter(record)
    return record


def test_record_outside_any_scope_has_no_ids_and_no_trace() -> None:
    """Verify the format fields exist even when telemetry is off, so the formatter never breaks."""
    record = _stamped_record()

    assert (record.trace_id, record.correlation) == ("-", "")


def test_ids_in_scope_are_rendered_and_unset_ones_are_left_out() -> None:
    """Verify only the ids that were set appear on the line."""
    with correlation_scope(CorrelationIds(review_id=REVIEW_ID, repo_id=7)):
        record = _stamped_record()

    assert record.correlation == f"review_id={REVIEW_ID} repo_id=7"


def test_ids_are_restored_when_the_scope_ends() -> None:
    """Verify one message's ids never leak into the next message handled by the same task."""
    with correlation_scope(CorrelationIds(repo_id=7)):
        pass

    assert _stamped_record().correlation == ""


def test_ids_are_restored_when_the_block_raises() -> None:
    """Verify a failing handler still clears its ids."""
    with pytest.raises(RuntimeError):
        with correlation_scope(CorrelationIds(repo_id=7)):
            raise RuntimeError("handler failed")

    assert _stamped_record().correlation == ""


def test_inner_scope_replaces_and_then_restores_the_outer_one() -> None:
    """Verify nested scopes behave like a stack."""
    with correlation_scope(CorrelationIds(repo_id=1)):
        with correlation_scope(CorrelationIds(repo_id=2)):
            inner = _stamped_record().correlation
        outer = _stamped_record().correlation

    assert (inner, outer) == ("repo_id=2", "repo_id=1")


def test_trace_id_is_the_active_spans_trace_as_32_hex_characters() -> None:
    """Verify the line carries the same id a trace viewer shows."""
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("work") as span:
        record = _stamped_record()

    assert record.trace_id == format(span.get_span_context().trace_id, "032x")


@pytest.mark.asyncio
async def test_ids_reach_work_run_in_a_thread() -> None:
    """Verify asyncio.to_thread keeps the ids, since the pipeline logs from worker threads."""
    with correlation_scope(CorrelationIds(review_id=REVIEW_ID)):
        record = await asyncio.to_thread(_stamped_record)

    assert record.correlation == f"review_id={REVIEW_ID}"
