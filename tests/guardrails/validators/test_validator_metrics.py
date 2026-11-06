"""
    The intake validators report their model call like every other caller, under the INTAKE_SCREEN label.
"""
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.guardrails.errors import GuardrailsInvocationError
from code_reviewer.guardrails.validators import base
from code_reviewer.guardrails.validators.code_detection import CodeDetectionValidator
from code_reviewer.schemas.intake import ScreeningVerdict
from code_reviewer.telemetry.metrics import PipelineMetrics
from tests.metric_points import LLM_CALL_DURATION, LLM_CALL_ERRORS, LLM_TOKENS, point_with, points_for

MODEL = "fake-screening-model"
LABEL = {"code_reviewer.code_key": "INTAKE_SCREEN", "code_reviewer.model": MODEL}
USAGE = {"input_tokens": 90, "output_tokens": 12, "total_tokens": 102}


class FakeScreeningLLM:
    """An LLMInterface whose model returns a fixed reply, or raises."""

    model_name = MODEL

    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self._reply = reply

    def create_model(self, schema: type, include_raw: bool = False) -> RunnableLambda:
        return RunnableLambda(self._answer)

    def _answer(self, _prompt: Any) -> dict[str, Any]:
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _reply(parsed: ScreeningVerdict | None, parsing_error: Exception | None = None) -> dict[str, Any]:
    return {"raw": AIMessage(content="", usage_metadata=USAGE), "parsed": parsed, "parsing_error": parsing_error}


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(
    monkeypatch: pytest.MonkeyPatch, isolated_pipeline_metrics: PipelineMetrics
) -> None:
    monkeypatch.setattr(base, "pipeline_metrics", isolated_pipeline_metrics)


def test_a_screening_call_is_timed_under_the_intake_label(metric_reader: InMemoryMetricReader) -> None:
    """Verify the call lands in the latency histogram of the INTAKE_SCREEN caller."""
    validator = CodeDetectionValidator(llm=FakeScreeningLLM(_reply(ScreeningVerdict(is_valid=True, reason="code"))))

    validator._validate("x = 1", {})

    assert point_with(metric_reader, LLM_CALL_DURATION, LABEL).count == 1


def test_a_screening_call_reports_its_tokens(metric_reader: InMemoryMetricReader) -> None:
    """Verify the usage on the raw reply is counted, even though only the parsed verdict is used."""
    validator = CodeDetectionValidator(llm=FakeScreeningLLM(_reply(ScreeningVerdict(is_valid=True, reason="code"))))

    validator._validate("x = 1", {})

    assert point_with(metric_reader, LLM_TOKENS, {**LABEL, "code_reviewer.token_type": "input"}).value == 90


def test_a_failing_model_call_is_counted_with_its_cause(metric_reader: InMemoryMetricReader) -> None:
    """Verify a provider failure is classified, and still raised as the guardrails error."""
    validator = CodeDetectionValidator(llm=FakeScreeningLLM(TimeoutError("slow")))

    with pytest.raises(GuardrailsInvocationError):
        validator._validate("x = 1", {})

    assert point_with(metric_reader, LLM_CALL_ERRORS, {"code_reviewer.cause": "timeout"}).value == 1


def test_an_unparsable_verdict_raises_instead_of_passing_the_file(metric_reader: InMemoryMetricReader) -> None:
    """Verify include_raw's silent parse failure is turned back into an error, so a bad reply never admits a file."""
    validator = CodeDetectionValidator(llm=FakeScreeningLLM(_reply(None, ValueError("not json"))))

    with pytest.raises(GuardrailsInvocationError):
        validator._validate("x = 1", {})

    assert points_for(metric_reader, LLM_CALL_ERRORS) == []
