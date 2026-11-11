"""
    Metric instruments for the review pipeline, recorded through the OpenTelemetry API only.
"""
import logging
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from enum import StrEnum

from opentelemetry import metrics
from opentelemetry.metrics import Meter

from code_reviewer.telemetry.output_quality import OutputQuality
from code_reviewer.telemetry.run_summary import RunSummary, TokenUsage
from code_reviewer.telemetry.run_usage import add_tokens_to_current_run

logger = logging.getLogger(__name__)

UsageListener = Callable[[str, str, TokenUsage], None]

LLM_LATENCY_BUCKETS_SECONDS =[0.5, 1, 2, 5, 10, 20, 30, 60, 120, 180, 300]
MODEL_TURN_BUCKETS = [1, 2, 3, 4, 6, 8, 12]
RATING_BUCKETS = [0, 20, 40, 60, 70, 80, 85, 90, 95, 100]
REVIEW_COST_BUCKETS_USD = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20]

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
VALIDATOR = "code_reviewer.validator"
AGENT_PAIR = "code_reviewer.agent_pair"


class AgentOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class PipelineMetrics:
    """Holds the pipeline's instruments so callers record events, not raw numbers and labels."""

    def __init__(self, meter: Meter) -> None:
        self._usage_listeners: list[UsageListener] = []
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

    def record_llm_usage(self, code_key: str, model: str, usage: TokenUsage) -> None:
        """Adds the tokens one real model call reported, one series per token type."""
        counts = {
            "input": usage.input_tokens,
            "output": usage.output_tokens,
            "reasoning": usage.reasoning_tokens,
            "cached": usage.cached_input_tokens,
        }
        for token_type, count in counts.items():
            self._tokens.add(count, {CODE_KEY: code_key, MODEL: model, TOKEN_TYPE: token_type})
        add_tokens_to_current_run(usage)
        for listener in self._usage_listeners:
            self._notify(listener, code_key, model, usage)

    def add_usage_listener(self, listener: UsageListener) -> None:
        """Registers a callback told the usage of every real model call, such as a cost counter kept elsewhere."""
        self._usage_listeners.append(listener)

    def record_run_summary(self, code_key: str, summary: RunSummary) -> None:
        """Reports the model turns and tool calls of one finished agent run."""
        self._model_turns.record(summary.model_turns, {CODE_KEY: code_key})
        for tool_call in summary.tool_calls:
            status = "error" if tool_call.failed else "success"
            self._tool_calls.add(1, {CODE_KEY: code_key, TOOL: tool_call.name, TOOL_STATUS: status})

    def record_agent_skip(self, code_key: str, reason: str) -> None:
        """Counts one agent that was skipped without running."""
        self._agent_skipped.add(1, {CODE_KEY: code_key, REASON: reason})

    def record_invented_review(self, code_key: str, result: str) -> None:
        """Counts one review that described code it was not given; result is `retried` or `failed`."""
        self._invented_reviews.add(1, {CODE_KEY: code_key, RESULT: result})

    def record_reasonless_reply(self, code_key: str, result: str) -> None:
        """Counts one empty review sent with no reasoning by a reasoning model; result is `retried` or `failed`."""
        self._reasonless_replies.add(1, {CODE_KEY: code_key, RESULT: result})

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

    def record_review_cost(self, cost_usd: float) -> None:
        """Reports what one finished review cost; a lower bound when some of its calls had no known price."""
        self._review_cost.record(cost_usd)

    def record_file_skipped(self, reason: str) -> None:
        """Counts one file that was left out of a review, by the reason the report gives."""
        self._files_skipped.add(1, {REASON: reason})

    def record_intake_rejection(self, validator: str) -> None:
        """Counts one file the intake screen turned down, by the validator that did."""
        self._intake_rejections.add(1, {VALIDATOR: validator})

    def record_incident_overlaps(self, agent_pairs: Sequence[str]) -> None:
        """Counts incident pairs from two different agents that point at the same lines."""
        for agent_pair in agent_pairs:
            self._incident_overlaps.add(1, {AGENT_PAIR: agent_pair})

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
        self._invented_reviews = meter.create_counter(
            "code_reviewer.agent.invented_reviews",
            unit="{review}",
            description="Reviews whose incidents were mostly about code the agent was not given",
        )
        self._reasonless_replies = meter.create_counter(
            "code_reviewer.agent.reasonless_replies",
            unit="{review}",
            description="Empty reviews that a reasoning model sent with no reasoning",
        )

    def _create_llm_instruments(self, meter: Meter) -> None:
        """Creates the instruments that describe individual model calls and their cost in tokens."""
        self._tokens = meter.create_counter(
            "code_reviewer.llm.tokens",
            unit="{token}",
            description="Tokens reported by real model calls; reasoning is part of output and cached is part of input",
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
        self._review_cost = meter.create_histogram(
            "code_reviewer.review.cost",
            unit="USD",
            description="Cost of one finished review; a lower bound when some model calls had no known price",
            explicit_bucket_boundaries_advisory=REVIEW_COST_BUCKETS_USD,
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
        self._incident_overlaps = meter.create_counter(
            "code_reviewer.agent.incident_overlaps",
            unit="{pair}",
            description=(
                "Pairs of incidents from two different agents that share a line; one incident "
                "overlapping several others is counted once per pair"
            ),
        )
        self._files_skipped = meter.create_counter(
            "code_reviewer.file.skipped", unit="{file}", description="Files left out of a review, by reason"
        )
        self._intake_rejections = meter.create_counter(
            "code_reviewer.intake.rejections", unit="{file}", description="Files the intake screen turned down"
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

    def _notify(self, listener: UsageListener, code_key: str, model: str, usage: TokenUsage) -> None:
        """A failing listener is logged and never reaches the model call that reported the usage."""
        try:
            listener(code_key, model, usage)
        except Exception:
            logger.exception("A usage listener failed for code_key=%s model=%s", code_key, model)

    def _record_agent_run(self, code_key: str, outcome: AgentOutcome, seconds: float) -> None:
        """Adds one observation to the agent run duration histogram."""
        self._agent_run_duration.record(seconds, {CODE_KEY: code_key, OUTCOME: outcome.value})


def outcome_of_failure(error: BaseException) -> AgentOutcome:
    """A hard timeout reaches the caller wrapped in another exception, so the cause is checked too."""
    if isinstance(error, TimeoutError) or isinstance(error.__cause__, TimeoutError):
        return AgentOutcome.TIMED_OUT
    return AgentOutcome.FAILED


pipeline_metrics = PipelineMetrics(metrics.get_meter("code_reviewer"))
