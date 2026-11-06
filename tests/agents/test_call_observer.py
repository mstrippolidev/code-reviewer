"""
    Tests for the model-call observer middleware: the error classifier on its own, and the middleware
    run through a real LangChain agent whose fake model fails on demand, since the point is to prove
    it sees every attempt the retry middleware makes.
"""
from typing import Any

import httpx
import ollama
import openai
import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from code_reviewer.agents.llm import call_observer
from code_reviewer.agents.llm.call_observer import build_model_call_observer, classify_llm_error
from code_reviewer.agents.llm.middleware import StructuredOutputNotCalledError
from code_reviewer.telemetry.metrics import PipelineMetrics
from code_reviewer.telemetry.run_usage import track_usage
from tests.metric_points import (
    LLM_CALL_DURATION,
    LLM_CALL_ERRORS,
    LLM_CALLS_IN_FLIGHT,
    LLM_TOKENS,
    point_with,
    points_for,
)

_REQUEST = httpx.Request("POST", "http://provider.test/v1/chat")


def _status_error(error_type: type[openai.APIStatusError], status_code: int) -> openai.APIStatusError:
    """An OpenAI client error as the SDK raises it for an HTTP status."""
    return error_type("provider error", response=httpx.Response(status_code, request=_REQUEST), body=None)


class _FlakyChatModel(BaseChatModel):
    """A chat model that raises each queued failure in turn, then answers normally."""

    failures: list[Any]
    usage: dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return "flaky"

    def _generate(self, messages: list, stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        if self.failures:
            raise self.failures.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="done", usage_metadata=self.usage))])


def _run_agent(
    failures: list[Exception],
    monkeypatch: pytest.MonkeyPatch,
    metrics: PipelineMetrics,
    usage: dict[str, Any] | None = None,
) -> None:
    """Runs one agent whose model fails as told, with the same retry-outside, observer-inside order the agents use."""
    monkeypatch.setattr(call_observer, "pipeline_metrics", metrics)
    retry = ModelRetryMiddleware(
        max_retries=2, retry_on=(openai.RateLimitError,), on_failure="error", initial_delay=0.0, jitter=False
    )
    agent = create_agent(
        model=_FlakyChatModel(failures=failures, usage=usage),
        tools=[],
        middleware=[retry, build_model_call_observer("VAR", "test-model")],
    )
    agent.invoke({"messages": [{"role": "user", "content": "review this"}]})


@pytest.mark.parametrize(
    "error,expected_cause",
    [
        (_status_error(openai.RateLimitError, 429), "rate_limit"),
        (_status_error(openai.InternalServerError, 503), "server_error"),
        (openai.APIConnectionError(request=_REQUEST), "connection"),
        (openai.APITimeoutError(request=_REQUEST), "timeout"),
        (httpx.ConnectError("refused"), "connection"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (ConnectionError("reset"), "connection"),
        (TimeoutError("hard timeout"), "timeout"),
        (ollama.ResponseError("busy", 429), "rate_limit"),
        (ollama.ResponseError("crashed", 500), "server_error"),
        (ollama.ResponseError("unreachable", -1), "connection"),
        (ollama.ResponseError("bad request", 400), "other"),
        (StructuredOutputValidationError("AgentOutput", ValueError("bad"), AIMessage(content="")), "schema_invalid"),
        (StructuredOutputNotCalledError("no tool call"), "no_tool_call"),
        (ValueError("unrelated"), "other"),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, BaseException) else value,
)
def test_classify_llm_error_names_the_cause_of_each_failure_type(error: BaseException, expected_cause: str) -> None:
    """Verify every failure type maps to its cause, with timeouts told apart from other connection errors.

    Both timeout classes are subclasses of the connection ones, so the order of the checks is what is under test.
    """
    assert classify_llm_error(error) == expected_cause


def test_observer_times_the_failed_attempt_and_the_retry_separately(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a rate limit followed by a success shows up as two timed model calls.

    The observer sits inside the retry middleware, so the failed attempt must not be hidden by the retry.
    """
    _run_agent([_status_error(openai.RateLimitError, 429)], monkeypatch, isolated_pipeline_metrics)

    assert point_with(metric_reader, LLM_CALL_DURATION, {"code_reviewer.model": "test-model"}).count == 2


def test_observer_counts_the_failed_attempt_under_its_cause(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the retried rate limit is counted once, as rate_limit, even though the run itself succeeded."""
    _run_agent([_status_error(openai.RateLimitError, 429)], monkeypatch, isolated_pipeline_metrics)

    assert point_with(metric_reader, LLM_CALL_ERRORS, {"code_reviewer.cause": "rate_limit"}).value == 1


def test_observer_labels_the_calls_with_the_agent_code_key(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the code_key given at build time reaches the metric labels."""
    _run_agent([], monkeypatch, isolated_pipeline_metrics)

    assert point_with(metric_reader, LLM_CALL_DURATION, {"code_reviewer.code_key": "VAR"}).count == 1


def test_observer_records_no_error_when_every_call_succeeds(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a clean run leaves the error counter empty."""
    _run_agent([], monkeypatch, isolated_pipeline_metrics)

    assert points_for(metric_reader, LLM_CALL_ERRORS) == []


def test_observer_leaves_no_call_in_flight_after_a_retried_run(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the in-flight gauge is back to zero after a failure and its retry."""
    _run_agent([_status_error(openai.RateLimitError, 429)], monkeypatch, isolated_pipeline_metrics)

    assert point_with(metric_reader, LLM_CALLS_IN_FLIGHT, {"code_reviewer.code_key": "VAR"}).value == 0


_USAGE = {
    "input_tokens": 120,
    "output_tokens": 30,
    "total_tokens": 150,
    "input_token_details": {"cache_read": 40},
    "output_token_details": {"reasoning": 10},
}


@pytest.mark.parametrize("token_type,expected", [("input", 120), ("output", 30), ("reasoning", 10), ("cached", 40)])
def test_observer_reports_the_tokens_of_each_model_call(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pipeline_metrics: PipelineMetrics,
    metric_reader: InMemoryMetricReader,
    token_type: str,
    expected: int,
) -> None:
    """Verify the usage a model reports is counted under the caller's label and the model name."""
    _run_agent([], monkeypatch, isolated_pipeline_metrics, usage=_USAGE)

    labels = {"code_reviewer.code_key": "VAR", "code_reviewer.model": "test-model", "code_reviewer.token_type": token_type}
    assert point_with(metric_reader, LLM_TOKENS, labels).value == expected


def test_observer_counts_no_tokens_for_an_attempt_that_raised(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a rate-limited attempt adds nothing, so only the retry that answered is counted."""
    _run_agent([_status_error(openai.RateLimitError, 429)], monkeypatch, isolated_pipeline_metrics, usage=_USAGE)

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": "input"}).value == 120


def test_the_tokens_of_a_real_agent_call_reach_the_block_it_ran_in(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    """Verify the whole chain: model call, observer, usage hook, and the running total of the enclosing block."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with provider.get_tracer("test").start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            _run_agent([_status_error(openai.RateLimitError, 429)], monkeypatch, isolated_pipeline_metrics, usage=_USAGE)

    attributes = exporter.get_finished_spans()[0].attributes
    assert (attributes["code_reviewer.tokens.input"], attributes["code_reviewer.llm_calls"]) == (120, 1)


def test_a_failing_usage_listener_leaves_the_model_call_and_the_agent_run_untouched(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify broken cost code cannot fail a run: the agent finishes and its tokens are still counted."""

    def broken(code_key: str, model: str, usage: Any) -> None:
        raise RuntimeError("cost code is broken")

    isolated_pipeline_metrics.add_usage_listener(broken)

    _run_agent([], monkeypatch, isolated_pipeline_metrics, usage=_USAGE)

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": "input"}).value == 120


def test_observer_counts_a_response_without_usage_as_zero_tokens(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify a provider that reports no usage does not break the call."""
    _run_agent([], monkeypatch, isolated_pipeline_metrics)

    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": "input"}).value == 0
