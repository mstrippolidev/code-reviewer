"""
    Turns the tokens of each model call into USD, using the prices the provider lists.
"""
from opentelemetry import metrics
from opentelemetry.metrics import Meter

from api.config.settings import ApiSettings
from api.observability.llm_prices import PriceBook
from code_reviewer.agents.llm.factory import build_llm
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices
from code_reviewer.telemetry.metrics import CODE_KEY, MODEL, pipeline_metrics
from code_reviewer.telemetry.run_summary import TokenUsage
from code_reviewer.telemetry.run_usage import add_cost_to_current_run, add_unpriced_call_to_current_run


def start_cost_tracking(settings: ApiSettings) -> PriceBook:
    """Starts refreshing the prices of the models in use and counts the cost of every model call from now on."""
    llm = build_llm()
    model_names = [llm.model_name, llm.for_fast_tier().model_name]
    price_book = PriceBook(llm, model_names, settings.llm_price_refresh_seconds)
    pipeline_metrics.add_usage_listener(LlmCostMetrics(metrics.get_meter("api"), price_book).on_usage)
    price_book.start()
    return price_book


class LlmCostMetrics:
    """Counts the cost of model calls, and the calls whose model has no known price."""

    def __init__(self, meter: Meter, price_book: PriceBook) -> None:
        self._price_book = price_book
        self._cost = meter.create_counter(
            "code_reviewer.llm.cost", unit="USD", description="Cost of real model calls at the provider's listed price"
        )
        self._unpriced_calls = meter.create_counter(
            "code_reviewer.llm.unpriced_calls", unit="{call}", description="Model calls whose model has no known price"
        )

    def on_usage(self, code_key: str, model: str, usage: TokenUsage) -> None:
        """Adds one call's cost, or counts it as unpriced when the model's price is not known."""
        labels = {CODE_KEY: code_key, MODEL: model}
        try:
            prices = self._price_book.price_of(model)
        except PriceUnavailableError:
            self._unpriced_calls.add(1, labels)
            add_unpriced_call_to_current_run()
            return
        cost = cost_of(usage, prices)
        self._cost.add(cost, labels)
        add_cost_to_current_run(cost)


def cost_of(usage: TokenUsage, prices: TokenPrices) -> float:
    """Bills input minus cached at the input price: reasoning is part of output, and cached is part of input."""
    cached_price = prices.cached_input_per_token
    if cached_price is None:
        cached_price = prices.input_per_token
    uncached_input = usage.input_tokens - usage.cached_input_tokens
    return (
        uncached_input * prices.input_per_token
        + usage.cached_input_tokens * cached_price
        + usage.output_tokens * prices.output_per_token
    )
