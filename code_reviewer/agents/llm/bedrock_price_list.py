"""
    Reads a Bedrock model's token prices from the AWS Price List API.
"""
import json
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from code_reviewer.agents.llm.pricing import PriceUnavailableError, TokenPrices

_PRICE_LIST_REGION = "us-east-1"
_SERVICE_CODES = ("AmazonBedrock", "AmazonBedrockFoundationModels")
_TIMEOUT_SECONDS = 10
_INPUT_SUFFIXES = ("-input-tokens", "-input-tokens-standard")
_OUTPUT_SUFFIXES = ("-output-tokens", "-output-tokens-standard")
_TOKENS_PER_UNIT = {"1k tokens": 1_000, "1m tokens": 1_000_000}


def fetch_bedrock_prices(price_list_name: str, region_code: str) -> TokenPrices:
    """Asks the Price List API for the model's standard on-demand input and output token prices in one region.

    Raises:
        PriceUnavailableError: If the API cannot be reached or does not list both prices clearly.
    """
    try:
        client = boto3.client(
            "pricing",
            region_name=_PRICE_LIST_REGION,
            config=Config(connect_timeout=_TIMEOUT_SECONDS, read_timeout=_TIMEOUT_SECONDS),
        )
        products = _products_of(client, price_list_name, region_code)
    except (BotoCoreError, ClientError) as error:
        raise PriceUnavailableError("Could not read the AWS Price List.") from error
    return prices_from(products, price_list_name)


def _products_of(client: Any, price_list_name: str, region_code: str) -> list[dict[str, Any]]:
    """Every product listed for the model in the region, under the first service code that has any."""
    filters = [
        {"Type": "TERM_MATCH", "Field": "model", "Value": price_list_name},
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region_code},
    ]
    for service_code in _SERVICE_CODES:
        pages = client.get_paginator("get_products").paginate(ServiceCode=service_code, Filters=filters)
        products = [json.loads(item) for page in pages for item in page["PriceList"]]
        if products:
            return products
    return []


def prices_from(products: list[dict[str, Any]], price_list_name: str) -> TokenPrices:
    """Picks the standard input and output price out of the products listed for one model and region.

    The tier is read from the usagetype, not from inferenceType: a batch product also says "Input tokens" there.
    """
    input_prices = _distinct_prices(products, _INPUT_SUFFIXES)
    output_prices = _distinct_prices(products, _OUTPUT_SUFFIXES)
    if len(input_prices) != 1 or len(output_prices) != 1:
        raise PriceUnavailableError(
            f"The AWS Price List has no single standard input and output token price for {price_list_name}."
        )
    return TokenPrices(input_per_token=input_prices.pop(), output_per_token=output_prices.pop())


def _distinct_prices(products: list[dict[str, Any]], usage_type_suffixes: tuple[str, ...]) -> set[float]:
    """The per-token prices of the standard-tier products, one entry each however many products repeat it."""
    return {
        _price_per_token(product)
        for product in products
        if _usage_type_of(product).endswith(usage_type_suffixes)
    }


def _usage_type_of(product: dict[str, Any]) -> str:
    return product.get("product", {}).get("attributes", {}).get("usagetype", "").lower()


def _price_per_token(product: dict[str, Any]) -> float:
    """Reads the first on-demand price dimension and converts its unit to a single token."""
    try:
        term = next(iter(product["terms"]["OnDemand"].values()))
        dimension = next(iter(term["priceDimensions"].values()))
        tokens_per_unit = _TOKENS_PER_UNIT[dimension["unit"].strip().lower()]
        return float(dimension["pricePerUnit"]["USD"]) / tokens_per_unit
    except (KeyError, StopIteration, TypeError, ValueError, AttributeError) as error:
        raise PriceUnavailableError("The AWS Price List entry has a shape or unit that is not understood.") from error
