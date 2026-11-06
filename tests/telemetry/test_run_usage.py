"""
    Tests that the tokens and cost of the model calls inside a block are added up, nested into the enclosing
    block, and reported on the block's own span and in the log, without ever affecting the block's result.
"""
import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from code_reviewer.telemetry import run_usage
from code_reviewer.telemetry.run_summary import TokenUsage
from code_reviewer.telemetry.run_usage import (
    add_abandoned_call_to_current_run,
    add_cost_to_current_run,
    add_tokens_to_current_run,
    add_unpriced_call_to_current_run,
    track_usage,
)

INPUT = "code_reviewer.tokens.input"
OUTPUT = "code_reviewer.tokens.output"
REASONING = "code_reviewer.tokens.reasoning"
CACHED = "code_reviewer.tokens.cached"
COST = "code_reviewer.cost_usd"
UNPRICED = "code_reviewer.unpriced_calls"
ABANDONED = "code_reviewer.abandoned_calls"
CALLS = "code_reviewer.llm_calls"


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def tracer(exporter: InMemorySpanExporter) -> Any:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test")


def _span(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    return next(span for span in exporter.get_finished_spans() if span.name == name)


def _call(input_tokens: int = 100, output_tokens: int = 20) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens, output_tokens=output_tokens, reasoning_tokens=5, cached_input_tokens=40
    )


def test_the_tokens_of_a_call_inside_a_block_land_on_its_span(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify all four token counts and the call count are written to the span the block ran under."""
    with tracer.start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            add_tokens_to_current_run(_call())

    attributes = _span(exporter, "agent").attributes
    assert (attributes[INPUT], attributes[OUTPUT], attributes[REASONING], attributes[CACHED], attributes[CALLS]) == (
        100, 20, 5, 40, 1,
    )


def test_several_calls_in_one_block_are_added_up(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify retries, tool round-trips and chunks all count toward the one block."""
    with tracer.start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            add_tokens_to_current_run(_call(100, 20))
            add_tokens_to_current_run(_call(50, 10))

    attributes = _span(exporter, "agent").attributes
    assert (attributes[INPUT], attributes[OUTPUT], attributes[CALLS]) == (150, 30, 2)


def test_cost_and_unpriced_calls_are_written_to_the_span(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify a span can say "cost unknown" separately from a cost of zero."""
    with tracer.start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            add_cost_to_current_run(0.002)
            add_cost_to_current_run(0.003)
            add_unpriced_call_to_current_run()

    attributes = _span(exporter, "agent").attributes
    assert (attributes[COST], attributes[UNPRICED]) == (pytest.approx(0.005), 1)


def test_an_abandoned_call_is_counted_on_the_span_and_every_enclosing_block(
    tracer: Any, exporter: InMemorySpanExporter
) -> None:
    """Verify a timed-out call, whose tokens are unknown, marks its block and the ones around it as lower bounds."""
    with tracer.start_as_current_span("file"):
        with track_usage("file=a.py"):
            with tracer.start_as_current_span("agent"):
                with track_usage("agent=DRY"):
                    add_abandoned_call_to_current_run()

    assert (_span(exporter, "agent").attributes[ABANDONED], _span(exporter, "file").attributes[ABANDONED]) == (1, 1)


def test_the_block_yields_its_running_total_so_a_caller_can_read_it_afterwards() -> None:
    """Verify the total is readable once the work inside is done, which is how a review's cost is reported."""
    with track_usage("review") as total:
        add_tokens_to_current_run(_call(100, 20))
        add_cost_to_current_run(0.25)

    assert (total.input_tokens, total.cost_usd) == (100, 0.25)


def test_a_block_with_no_calls_writes_zeros(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify an agent that made no model call still reports, so a missing attribute means a missing report."""
    with tracer.start_as_current_span("agent"):
        with track_usage("agent=CMT"):
            pass

    attributes = _span(exporter, "agent").attributes
    assert (attributes[INPUT], attributes[COST], attributes[CALLS]) == (0, 0, 0)


def test_a_nested_block_adds_to_the_block_around_it(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify the file's total contains each agent's, so the review's total is the sum of everything inside."""
    with tracer.start_as_current_span("file"):
        with track_usage("file=a.py"):
            with tracer.start_as_current_span("agent_one"):
                with track_usage("agent=ONE"):
                    add_tokens_to_current_run(_call(100, 20))
                    add_cost_to_current_run(0.01)
            with tracer.start_as_current_span("agent_two"):
                with track_usage("agent=TWO"):
                    add_tokens_to_current_run(_call(30, 5))
                    add_cost_to_current_run(0.002)

    assert _span(exporter, "agent_one").attributes[INPUT] == 100
    assert _span(exporter, "agent_two").attributes[INPUT] == 30
    assert _span(exporter, "file").attributes[INPUT] == 130
    assert _span(exporter, "file").attributes[COST] == pytest.approx(0.012)


def test_a_sibling_block_does_not_see_the_others_calls(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify two agents running one after another each report only their own."""
    with tracer.start_as_current_span("first"):
        with track_usage("agent=ONE"):
            add_tokens_to_current_run(_call(100, 20))
    with tracer.start_as_current_span("second"):
        with track_usage("agent=TWO"):
            add_tokens_to_current_run(_call(7, 1))

    assert _span(exporter, "second").attributes[INPUT] == 7


def test_calls_outside_any_block_do_nothing_and_do_not_raise() -> None:
    """Verify indexing and other callers with no review around them are unaffected."""
    add_tokens_to_current_run(_call())
    add_cost_to_current_run(1.0)
    add_unpriced_call_to_current_run()


def test_calls_from_several_threads_are_all_counted(tracer: Any, exporter: InMemorySpanExporter) -> None:
    """Verify chunk agents running in parallel threads lose no update, using the same copy_context idiom as the pipeline."""
    with tracer.start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(contextvars.copy_context().run, add_tokens_to_current_run, _call(1, 1))
                    for _ in range(200)
                ]
                for future in futures:
                    future.result()

    attributes = _span(exporter, "agent").attributes
    assert (attributes[INPUT], attributes[CALLS]) == (200, 200)


def test_the_totals_are_logged_with_the_label(
    tracer: Any, exporter: InMemorySpanExporter, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify the log line names the block and carries the numbers, so it can be read without the trace."""
    caplog.set_level(logging.INFO, logger=run_usage.logger.name)

    with tracer.start_as_current_span("agent"):
        with track_usage("agent=VAR file=a.py"):
            add_tokens_to_current_run(_call(100, 20))
            add_cost_to_current_run(0.0042)

    assert "usage agent=VAR file=a.py input=100 output=20 reasoning=5 cached=40 cost_usd=0.004200" in caplog.text


def test_an_exception_in_the_block_passes_through_and_its_totals_are_still_published(
    tracer: Any, exporter: InMemorySpanExporter
) -> None:
    """Verify a failed agent run is not hidden and still reports what it spent before failing."""
    with tracer.start_as_current_span("agent"):
        with pytest.raises(RuntimeError, match="provider down"):
            with track_usage("agent=VAR"):
                add_tokens_to_current_run(_call(100, 20))
                raise RuntimeError("provider down")

    assert _span(exporter, "agent").attributes[INPUT] == 100


def test_a_span_that_cannot_be_written_does_not_change_the_blocks_result(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify broken telemetry costs the totals and nothing else."""

    class BrokenSpan:
        def set_attributes(self, attributes: dict) -> None:
            raise RuntimeError("exporter down")

    monkeypatch.setattr(run_usage.trace, "get_current_span", lambda: BrokenSpan())

    with track_usage("agent=VAR"):
        result = "review"

    assert result == "review"
    assert "Could not publish the usage of agent=VAR" in caplog.text


def test_a_failure_while_adding_never_reaches_the_caller(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify accounting that breaks cannot break the model call that is being measured."""

    def explode(self: Any, usage: TokenUsage) -> None:
        raise RuntimeError("accounting bug")

    monkeypatch.setattr(run_usage.RunUsage, "add_tokens", explode)

    with track_usage("agent=VAR"):
        add_tokens_to_current_run(_call())

    assert "Could not add to the usage of the current run" in caplog.text
