"""
    Each provider answers what a token of a model costs, or says it cannot. Fakes only: no network, no AWS.
"""
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from botocore.exceptions import NoCredentialsError

from code_reviewer.agents.llm import bedrock, bedrock_price_list, openrouter
from code_reviewer.agents.llm.bedrock import BedrockLLM
from code_reviewer.agents.llm.bedrock_price_list import fetch_bedrock_prices, prices_from
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices

MODEL = "deepseek/deepseek-v4-pro"
PRICE_LIST_NAME = "Claude Test"
REGION = "us-east-2"


def _listing(*entries: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": list(entries)}, request=httpx.Request("GET", "http://openrouter.test"))


def _entry(model_id: str, **pricing: str) -> dict[str, Any]:
    return {"id": model_id, "pricing": pricing}


def _serve(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> None:
    """Makes OpenRouter's price request answer with the given response, or raise the given error."""

    def get(url: str, **kwargs: Any) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(openrouter.httpx, "get", get)


def test_openrouter_reads_the_prices_listed_for_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the per-token strings become numbers, cache price included."""
    _serve(monkeypatch, _listing(_entry(MODEL, prompt="0.000001", completion="0.000004", input_cache_read="0.0000002")))

    prices = OpenRouter().fetch_token_prices(MODEL)

    assert prices == TokenPrices(input_per_token=1e-6, output_per_token=4e-6, cached_input_per_token=2e-7)


def test_openrouter_leaves_the_cache_price_unset_when_the_model_lists_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a model without input_cache_read is not given an invented cache price."""
    _serve(monkeypatch, _listing(_entry(MODEL, prompt="0.000001", completion="0.000004")))

    assert OpenRouter().fetch_token_prices(MODEL).cached_input_per_token is None


def test_openrouter_does_not_guess_the_price_of_a_model_it_does_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an id that is not in the list is unavailable, not matched loosely to a similar one."""
    _serve(monkeypatch, _listing(_entry("other/model", prompt="0.1", completion="0.2")))

    with pytest.raises(PriceUnavailableError):
        OpenRouter().fetch_token_prices(MODEL)


def test_openrouter_reports_an_unreachable_service_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a network failure becomes PriceUnavailableError, the only error callers have to know."""
    _serve(monkeypatch, httpx.ConnectError("refused"))

    with pytest.raises(PriceUnavailableError):
        OpenRouter().fetch_token_prices(MODEL)


def test_openrouter_reports_an_unexpected_answer_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify an answer without the expected list does not escape as a KeyError."""
    _serve(monkeypatch, httpx.Response(200, json={"error": "nope"}, request=httpx.Request("GET", "http://x")))

    with pytest.raises(PriceUnavailableError):
        OpenRouter().fetch_token_prices(MODEL)


def test_openrouter_reports_prices_that_are_not_numbers_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a listing with unreadable prices is unavailable, since a wrong number is worse than none."""
    _serve(monkeypatch, _listing(_entry(MODEL, prompt="free", completion="0.1")))

    with pytest.raises(PriceUnavailableError):
        OpenRouter().fetch_token_prices(MODEL)


def test_ollama_models_are_free() -> None:
    """Verify a local model costs nothing per token, whatever its name."""
    assert OllamaLLM().fetch_token_prices("deepseek-r1:14b") == TokenPrices.free()


def _product(kind: str, unit: str, usd: str, tier: str = "") -> dict[str, Any]:
    """A Price List product as AWS returns it.

    inferenceType says "Input tokens" even for a batch product, as the real list does; only the usagetype
    tells the tier apart.
    """
    suffix = f"-{tier}" if tier else ""
    attributes = {
        "model": PRICE_LIST_NAME,
        "inferenceType": f"{kind.capitalize()} tokens",
        "usagetype": f"USE2-Test-{kind}-tokens{suffix}",
    }
    dimension = {"unit": unit, "pricePerUnit": {"USD": usd}}
    return {
        "product": {"attributes": attributes},
        "terms": {"OnDemand": {"TERM": {"priceDimensions": {"DIMENSION": dimension}}}},
    }


def _standard_pair() -> list[dict[str, Any]]:
    return [_product("input", "1K tokens", "0.003"), _product("output", "1K tokens", "0.015")]


def test_bedrock_converts_a_price_per_thousand_tokens_to_a_price_per_token() -> None:
    """Verify the unit on the price dimension is applied."""
    prices = prices_from(_standard_pair(), PRICE_LIST_NAME)

    assert (prices.input_per_token, prices.output_per_token) == (pytest.approx(3e-6), pytest.approx(1.5e-5))


def test_bedrock_converts_a_price_per_million_tokens_to_a_price_per_token() -> None:
    """Verify a listing in millions is read as such, not as thousands."""
    products = [_product("input", "1M tokens", "3.00"), _product("output", "1M tokens", "15.00")]

    assert prices_from(products, PRICE_LIST_NAME).input_per_token == pytest.approx(3e-6)


def test_bedrock_refuses_a_unit_it_does_not_know() -> None:
    """Verify an unfamiliar unit is unavailable instead of being read as per token."""
    products = [_product("input", "1 image", "0.003"), _product("output", "1K tokens", "0.015")]

    with pytest.raises(PriceUnavailableError):
        prices_from(products, PRICE_LIST_NAME)


def test_bedrock_needs_both_the_input_and_the_output_price() -> None:
    """Verify a listing with only one of the two prices is unavailable."""
    with pytest.raises(PriceUnavailableError):
        prices_from([_product("input", "1K tokens", "0.003")], PRICE_LIST_NAME)


def test_bedrock_ignores_batch_flex_and_priority_products() -> None:
    """Verify only the standard tier is priced, though a batch product also calls itself "Input tokens"."""
    cheaper_and_dearer = [
        _product("input", "1K tokens", "0.0001", tier="batch"),
        _product("input", "1K tokens", "0.0001", tier="flex"),
        _product("input", "1K tokens", "0.0099", tier="priority"),
        _product("output", "1K tokens", "0.0001", tier="batch"),
        _product("output", "1K tokens", "0.0099", tier="priority"),
    ]

    with pytest.raises(PriceUnavailableError):
        prices_from(cheaper_and_dearer, PRICE_LIST_NAME)


def test_bedrock_takes_the_standard_price_when_other_tiers_are_listed_beside_it() -> None:
    """Verify the batch price listed first does not win over the standard one."""
    products = [_product("input", "1K tokens", "0.0001", tier="batch"), *_standard_pair()]

    assert prices_from(products, PRICE_LIST_NAME).input_per_token == pytest.approx(3e-6)


def test_bedrock_accepts_the_same_standard_price_listed_under_two_product_families() -> None:
    """Verify the plain and the explicit "-standard" listings, which the real list carries, count as one price."""
    products = [*_standard_pair(), _product("input", "1K tokens", "0.003", tier="standard")]

    assert prices_from(products, PRICE_LIST_NAME).input_per_token == pytest.approx(3e-6)


def test_bedrock_refuses_to_choose_between_two_different_standard_prices() -> None:
    """Verify a conflict is unavailable instead of an arbitrary pick."""
    products = [*_standard_pair(), _product("input", "1K tokens", "0.004", tier="standard")]

    with pytest.raises(PriceUnavailableError):
        prices_from(products, PRICE_LIST_NAME)


def test_bedrock_without_a_price_list_name_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the missing mapping to the Price List is reported, not guessed from the model id."""
    monkeypatch.setattr(bedrock, "get_settings", lambda: SimpleNamespace(bedrock_price_list_model=""))

    with pytest.raises(PriceUnavailableError, match="BEDROCK_PRICE_LIST_MODEL"):
        BedrockLLM().fetch_token_prices("deepseek.v3-v1:0")


def test_bedrock_looks_up_the_configured_name_in_the_configured_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the Price List name and the region the model runs in are what get looked up."""
    looked_up: list[tuple[str, str]] = []

    def fetch(price_list_name: str, region_code: str) -> TokenPrices:
        looked_up.append((price_list_name, region_code))
        return TokenPrices.free()

    monkeypatch.setattr(bedrock, "get_settings", lambda: SimpleNamespace(bedrock_price_list_model=PRICE_LIST_NAME))
    monkeypatch.setattr(bedrock.settings, "bedrock_region", REGION)
    monkeypatch.setattr(bedrock, "fetch_bedrock_prices", fetch)

    BedrockLLM().fetch_token_prices("deepseek.v3-v1:0")

    assert looked_up == [(PRICE_LIST_NAME, REGION)]


class _FakePricingClient:
    """Answers get_products per service code, the way the paginator hands back pages of JSON strings."""

    def __init__(self, products_by_service: dict[str, list[dict[str, Any]]]) -> None:
        self._products_by_service = products_by_service
        self.asked: list[str] = []
        self.filters: list[dict[str, str]] = []

    def get_paginator(self, operation: str) -> "_FakePricingClient":
        return self

    def paginate(self, ServiceCode: str, Filters: list[dict[str, str]]) -> list[dict[str, list[str]]]:
        self.asked.append(ServiceCode)
        self.filters = Filters
        return [{"PriceList": [json.dumps(item) for item in self._products_by_service.get(ServiceCode, [])]}]


def test_the_price_list_falls_through_to_the_next_service_code_when_the_first_has_no_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a model listed only under the second service code is still found."""
    client = _FakePricingClient({"AmazonBedrockFoundationModels": _standard_pair()})
    monkeypatch.setattr(bedrock_price_list.boto3, "client", lambda *args, **kwargs: client)

    prices = fetch_bedrock_prices(PRICE_LIST_NAME, REGION)

    assert (client.asked, prices.input_per_token) == (
        ["AmazonBedrock", "AmazonBedrockFoundationModels"],
        pytest.approx(3e-6),
    )


def test_the_price_list_is_asked_for_one_model_in_one_region(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the request is filtered by region, since the same model is priced differently per region."""
    client = _FakePricingClient({"AmazonBedrock": _standard_pair()})
    monkeypatch.setattr(bedrock_price_list.boto3, "client", lambda *args, **kwargs: client)

    fetch_bedrock_prices(PRICE_LIST_NAME, REGION)

    assert client.filters == [
        {"Type": "TERM_MATCH", "Field": "model", "Value": PRICE_LIST_NAME},
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": REGION},
    ]


def test_the_price_list_reports_an_aws_failure_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify missing credentials or a refused call become PriceUnavailableError."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise NoCredentialsError()

    monkeypatch.setattr(bedrock_price_list.boto3, "client", refuse)

    with pytest.raises(PriceUnavailableError):
        fetch_bedrock_prices(PRICE_LIST_NAME, REGION)
