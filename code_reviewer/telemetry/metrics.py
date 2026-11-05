"""
    Metric instruments for the review pipeline, recorded through the OpenTelemetry API only.
"""
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.metrics import Meter

from code_reviewer.telemetry.output_quality import OutputQuality
from code_reviewer.telemetry.run_summary import RunSummary

LLM_LATENCY_BUCKETS_SECONDS = [0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180, 300]
MODEL_TURN_BUCKETS = [1, 2, 3, 4, 6, 8, 12]
RATING_BUCKETS = [0, 20, 40, 60, 70, 80, 85, 90, 95, 100]

CODE_KEY = "code_reviewer.code_key"
OUTCOME = "code_reviewer.outcome"
MODEL = "code_reviewer.model"
CAUSE = "code_reviewer.cause"
TOKEN_TYPE = "code_reviewer.token_type"
TOOL = "code_reviewer.tool"
TOOL_STATUS = "code_reviewer.tool_status"
REASON = "code_reviewer.reason"
PRIORITY = "code_reviewer.priority"
RESULT = "code_reviewer.result"


class AgentOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class PipelineMetrics:
    """Holds the pipeline's instruments so callers record events, not raw numbers and labels."""

    def __init__(self, meter: Meter) -> None:
        self._create_agent_instruments(meter)
        self._create_llm_instruments(meter)
        self._create_output_quality_instruments(meter)

    @contextmanager
    def track_agent_run(self, code_key: str) -> Iterator[None]:
        """Times the enclosed agent run and records how it ended, re-raising any failure."""
        started = time.perf_counter()
        outcome = AgentOutcome.COMPLETED
        try:
            yield
        except BaseException as error:
            outcome = outcome_of_failure(error)
            raise
        finally:
            self._record_agent_run(code_key, outcome, time.perf_counter() - started)

    @contextmanager
    def track_llm_call(
        self, code_key: str, model: str, classify_error: Callable[[BaseException], str]
    ) -> Iterator[None]:
        """Counts one real model call in flight, times it, and records the cause if it fails."""
        labels = {CODE_KEY: code_key, MODEL: model}
        self._llm_calls_in_flight.add(1, labels)
        started = time.perf_counter()
        try:
            yield
        except BaseException as error:
            self._llm_call_errors.add(1, {**labels, CAUSE: classify_error(error)})
            raise
        finally:
            self._llm_calls_in_flight.add(-1, labels)
            self._llm_call_duration.record(time.perf_counter() - started, labels)

    def record_run_summary(self, code_key: str, model: str, summary: RunSummary) -> None:
        """Reports the tokens, model turns and tool calls of one finished agent run."""
        self._record_tokens(code_key, model, summary)
        self._model_turns.record(summary.model_turns, {CODE_KEY: code_key})
        for tool_call in summary.tool_calls:
            status = "error" if tool_call.failed else "success"
            self._tool_calls.add(1, {CODE_KEY: code_key, TOOL: tool_call.name, TOOL_STATUS: status})

    def record_agent_skip(self, code_key: str, reason: str) -> None:
        """Counts one agent that was skipped without running."""
        self._agent_skipped.add(1, {CODE_KEY: code_key, REASON: reason})

    def record_output_quality(self, code_key: str, quality: OutputQuality) -> None:
        """Reports what one agent concluded about one file."""
        labels = {CODE_KEY: code_key}
        result = "empty" if quality.is_empty else "with_incidents"
        self._agent_results.add(1, {**labels, RESULT: result})
        self._agent_rating.record(quality.rating, labels)
        for priority in quality.incident_priorities:
            self._agent_incidents.add(1, {**labels, PRIORITY: priority})
        self._invalid_line_positions.add(quality.invalid_line_positions, labels)

    def record_review_rating(self, rating: float) -> None:
        """Reports the overall rating of one finished review."""
        self._review_rating.record(rating)

    def _create_agent_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe an agent run as a whole."""
        self._agent_run_duration = meter.create_histogram(
            "code_reviewer.agent.run.duration",
            unit="s",
            description="Wall time of one agent run on one file",
            explicit_bucket_boundaries_advisory=LLM_LATENCY_BUCKETS_SECONDS,
        )
        self._model_turns = meter.create_histogram(
            "code_reviewer.agent.model_turns",
            unit="{turn}",
            description="Model turns taken by one agent run, tool round-trips and corrections included",
            explicit_bucket_boundaries_advisory=MODEL_TURN_BUCKETS,
        )
        self._tool_calls = meter.create_counter(
            "code_reviewer.agent.tool_calls", unit="{call}", description="Tool calls made by agents"
        )
        self._agent_skipped = meter.create_counter(
            "code_reviewer.agent.skipped", unit="{agent}", description="Agents skipped without running"
        )

    def _create_llm_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe individual model calls and their cost in tokens."""
        self._tokens = meter.create_counter(
            "code_reviewer.llm.tokens",
            unit="{token}",
            description="Tokens used by agent runs; reasoning is part of output and cached is part of input",
        )
        self._llm_call_duration = meter.create_histogram(
            "code_reviewer.llm.call.duration",
            unit="s",
            description="Wall time of one real model call, each retry counted on its own",
            explicit_bucket_boundaries_advisory=LLM_LATENCY_BUCKETS_SECONDS,
        )
        self._llm_call_errors = meter.create_counter(
            "code_reviewer.llm.call.errors", unit="{error}", description="Failed model calls by cause"
        )
        self._llm_calls_in_flight = meter.create_up_down_counter(
            "code_reviewer.llm.calls.in_flight", unit="{call}", description="Model calls running right now"
        )

    def _create_output_quality_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe what agents concluded, not how their runs went."""
        self._agent_results = meter.create_counter(
            "code_reviewer.agent.results", unit="{result}", description="Agent results per file, empty or with incidents"
        )
        self._agent_incidents = meter.create_counter(
            "code_reviewer.agent.incidents", unit="{incident}", description="Incidents reported by agents, by priority"
        )
        self._agent_rating = meter.create_histogram(
            "code_reviewer.agent.rating",
            unit="{point}",
            description="Rating of one agent on one file",
            explicit_bucket_boundaries_advisory=RATING_BUCKETS,
        )
        self._invalid_line_positions = meter.create_counter(
            "code_reviewer.agent.invalid_line_positions",
            unit="{incident}",
            description="Incidents whose line_position is malformed or outside the file",
        )
        self._review_rating = meter.create_histogram(
            "code_reviewer.review.rating",
            unit="{point}",
            description="Overall rating of one finished review",
            explicit_bucket_boundaries_advisory=RATING_BUCKETS,
        )

    def _record_agent_run(self, code_key: str, outcome: AgentOutcome, seconds: float) -> None:
        """Adds one observation to the agent run duration histogram."""
        self._agent_run_duration.record(seconds, {CODE_KEY: code_key, OUTCOME: outcome.value})

    def _record_tokens(self, code_key: str, model: str, summary: RunSummary) -> None:
        """Adds one run's token counts to the token counter, one series per token type."""
        counts = {
            "input": summary.input_tokens,
            "output": summary.output_tokens,
            "reasoning": summary.reasoning_tokens,
            "cached": summary.cached_input_tokens,
        }
        for token_type, count in counts.items():
            self._tokens.add(count, {CODE_KEY: code_key, MODEL: model, TOKEN_TYPE: token_type})


def outcome_of_failure(error: BaseException) -> AgentOutcome:
    """A hard timeout reaches the caller wrapped in another exception, so the cause is checked too."""
    if isinstance(error, TimeoutError) or isinstance(error.__cause__, TimeoutError):
        return AgentOutcome.TIMED_OUT
    return AgentOutcome.FAILED


pipeline_metrics = PipelineMetrics(metrics.get_meter("code_reviewer"))
