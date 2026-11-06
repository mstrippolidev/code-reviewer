"""
    Tests that token usage turns into USD at the provider's listed price, and that an unpriced model is counted apart.
"""
import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from api.observability.llm_cost import LlmCostMetrics, cost_of
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices
from code_reviewer.telemetry.metrics import PipelineMetrics
from code_reviewer.telemetry.run_summary import TokenUsage
from code_reviewer.telemetry.run_usage import track_usage
from tests.metric_points import LLM_COST, LLM_TOKENS, LLM_UNPRICED_CALLS, point_with, points_for

MODEL = "vendor/priced-model"
EXPLODING_MODEL = "vendor/exploding-model"
PRICES = TokenPrices(input_per_token=0.000001, output_per_token=0.000004, cached_input_per_token=0.0000002)


class FakePriceBook:
    """Knows the price of one model, fails in an unexpected way for another, and has no price for the rest."""

    def price_of(self, model_name: str) -> TokenPrices:
        if model_name == EXPLODING_MODEL:
            raise RuntimeError("the price book is broken")
        if model_name != MODEL:
            raise PriceUnavailableError(f"No price is known for {model_name}.")
        return PRICES


@pytest.fixture
def meter_provider(metric_reader: InMemoryMetricReader) -> MeterProvider:
    return MeterProvider(metric_readers=[metric_reader])


@pytest.fixture
def cost_metrics(meter_provider: MeterProvider) -> LlmCostMetrics:
    return LlmCostMetrics(meter_provider.get_meter("test"), FakePriceBook())


@pytest.fixture
def pipeline_metrics_on_same_provider(meter_provider: MeterProvider) -> PipelineMetrics:
    return PipelineMetrics(meter_provider.get_meter("test"))


def test_cost_of_bills_input_and_output_at_their_own_prices() -> None:
    """Verify a plain call is input x input price + output x output price."""
    cost = cost_of(TokenUsage(input_tokens=1000, output_tokens=500), PRICES)

    assert cost == pytest.approx(1000 * 0.000001 + 500 * 0.000004)


def test_cost_of_bills_cached_tokens_at_the_cache_price_and_not_twice() -> None:
    """Verify cached tokens are part of input: they leave the input price and pay the cache price instead."""
    cost = cost_of(TokenUsage(input_tokens=1000, cached_input_tokens=400), PRICES)

    assert cost == pytest.approx(600 * 0.000001 + 400 * 0.0000002)


def test_cost_of_bills_cached_tokens_at_the_input_price_when_the_provider_lists_no_cache_price() -> None:
    """Verify a missing cache price is not read as free."""
    prices = TokenPrices(input_per_token=0.000001, output_per_token=0.000004)

    cost = cost_of(TokenUsage(input_tokens=1000, cached_input_tokens=400), prices)

    assert cost == pytest.approx(1000 * 0.000001)


def test_cost_of_does_not_bill_reasoning_a_second_time() -> None:
    """Verify reasoning tokens, which are already inside output, add nothing."""
    cost = cost_of(TokenUsage(output_tokens=500, reasoning_tokens=300), PRICES)

    assert cost == pytest.approx(500 * 0.000004)


def test_cost_of_a_free_model_is_zero() -> None:
    """Verify a local model costs nothing whatever it used."""
    assert cost_of(TokenUsage(input_tokens=9000, output_tokens=9000), TokenPrices.free()) == 0


def test_a_priced_call_adds_its_cost_under_its_caller_and_model(
    cost_metrics: LlmCostMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify the cost lands on the series of the caller that made the call."""
    cost_metrics.on_usage("DRY_JUDGE", MODEL, TokenUsage(input_tokens=1000, output_tokens=500))

    point = point_with(metric_reader, LLM_COST, {"code_reviewer.code_key": "DRY_JUDGE", "code_reviewer.model": MODEL})
    assert point.value == pytest.approx(0.003)


def test_two_calls_of_one_caller_add_up(cost_metrics: LlmCostMetrics, metric_reader: InMemoryMetricReader) -> None:
    """Verify the counter sums calls instead of keeping the last one."""
    cost_metrics.on_usage("VAR", MODEL, TokenUsage(input_tokens=1000))
    cost_metrics.on_usage("VAR", MODEL, TokenUsage(input_tokens=1000))

    assert point_with(metric_reader, LLM_COST, {"code_reviewer.code_key": "VAR"}).value == pytest.approx(0.002)


def test_a_call_to_a_model_without_a_price_is_counted_as_unpriced_and_adds_no_cost(
    cost_metrics: LlmCostMetrics, metric_reader: InMemoryMetricReader
) -> None:
    """Verify an unknown model shows up as a gap and never as a made-up number."""
    cost_metrics.on_usage("VAR", "vendor/unknown-model", TokenUsage(input_tokens=1000))

    unpriced = point_with(metric_reader, LLM_UNPRICED_CALLS, {"code_reviewer.model": "vendor/unknown-model"})
    assert (unpriced.value, points_for(metric_reader, LLM_COST)) == (1, [])


def _span_attributes_of_a_block(cost_metrics: LlmCostMetrics, model: str) -> dict[str, float]:
    """Runs one priced or unpriced call inside a tracked block and returns the attributes the block wrote."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("test").start_as_current_span("agent"):
        with track_usage("agent=VAR"):
            cost_metrics.on_usage("VAR", model, TokenUsage(input_tokens=1000, output_tokens=500))
    return dict(exporter.get_finished_spans()[0].attributes)


def test_the_cost_of_a_call_is_added_to_the_block_it_ran_in(cost_metrics: LlmCostMetrics) -> None:
    """Verify the agent's span gets the dollars, not only the cost counter."""
    attributes = _span_attributes_of_a_block(cost_metrics, MODEL)

    assert (attributes["code_reviewer.cost_usd"], attributes["code_reviewer.unpriced_calls"]) == (
        pytest.approx(0.003),
        0,
    )


def test_a_call_with_no_known_price_marks_the_block_instead_of_adding_cost(cost_metrics: LlmCostMetrics) -> None:
    """Verify "cost unknown" is visible on the span and the cost stays a lower bound, not a guess."""
    attributes = _span_attributes_of_a_block(cost_metrics, "vendor/unknown-model")

    assert (attributes["code_reviewer.cost_usd"], attributes["code_reviewer.unpriced_calls"]) == (0, 1)


def test_a_registered_cost_listener_receives_the_usage_of_a_model_call(
    metric_reader: InMemoryMetricReader,
    pipeline_metrics_on_same_provider: PipelineMetrics,
    cost_metrics: LlmCostMetrics,
) -> None:
    """Verify the hook feeds the cost counter through record_llm_usage, next to the token counters."""
    pipeline_metrics_on_same_provider.add_usage_listener(cost_metrics.on_usage)

    pipeline_metrics_on_same_provider.record_llm_usage("TEST", MODEL, TokenUsage(input_tokens=1000))

    assert point_with(metric_reader, LLM_COST, {"code_reviewer.code_key": "TEST"}).value == pytest.approx(0.001)
    assert point_with(metric_reader, LLM_TOKENS, {"code_reviewer.token_type": "input"}).value == 1000


def test_a_cost_calculation_that_fails_never_reaches_the_model_call(
    metric_reader: InMemoryMetricReader,
    pipeline_metrics_on_same_provider: PipelineMetrics,
    cost_metrics: LlmCostMetrics,
) -> None:
    """Verify broken cost code only loses the cost, and the token counters were already recorded."""
    pipeline_metrics_on_same_provider.add_usage_listener(cost_metrics.on_usage)

    pipeline_metrics_on_same_provider.record_llm_usage("TEST", EXPLODING_MODEL, TokenUsage(input_tokens=700))
    pipeline_metrics_on_same_provider.record_llm_usage("TEST", MODEL, TokenUsage(input_tokens=1000))

    tokens = points_for(metric_reader, LLM_TOKENS)
    assert sum(point.value for point in tokens if point.attributes["code_reviewer.token_type"] == "input") == 1700
    assert point_with(metric_reader, LLM_COST, {"code_reviewer.code_key": "TEST"}).value == pytest.approx(0.001)
