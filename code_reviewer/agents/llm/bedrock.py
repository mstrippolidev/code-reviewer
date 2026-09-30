"""
    LLMInterface implementation backed by AWS Bedrock's Converse API.
"""
from typing import Any

from botocore.config import Config
from langchain.agents.structured_output import ProviderStrategy, ResponseFormat

from code_reviewer.agents.llm.base import LLMInterface, T
from code_reviewer.config.settings import get_settings

settings = get_settings()


class BedrockLLM(LLMInterface[T]):
    """Builds chat models backed by AWS Bedrock's Converse API."""

    def _get_model_name(self) -> str:
        return settings.bedrock_llm_model

    def _get_model_provider(self) -> str:
        return "bedrock_converse"

    def _get_base_url(self) -> str | None:
        return None

    def _get_extra_kwargs(self) -> dict[str, Any]:
        timeout = get_settings().llm_call_timeout_seconds
        return {
            "region_name": settings.bedrock_llm_region,
            "config": Config(connect_timeout=timeout, read_timeout=timeout),
        }

    def build_response_format(self, schema: type[T]) -> ResponseFormat[T]:
        return ProviderStrategy(schema)
