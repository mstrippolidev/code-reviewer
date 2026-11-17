"""
    Real-model integration tests for BedrockLLM, validated against AWS
    Bedrock itself rather than mocked — see Testing Conventions.
"""
import pytest
from langchain_core.tools import tool
from pydantic import BaseModel

from code_reviewer.agents.llm.bedrock import BedrockLLM
from code_reviewer.agents.llm.output_cap import OutputTruncatedError
from code_reviewer.config.settings import get_settings


class _Greeting(BaseModel):
    language: str
    greeting: str


@tool
def _get_capital(country: str) -> str:
    """Return the capital city of a country."""
    return "Paris" if country.lower() == "france" else "unknown"


@pytest.mark.bedrock
def test_raw_model_returns_a_real_completion() -> None:
    """Verify the raw ChatBedrockConverse model responds with real text."""
    model = BedrockLLM().create_raw_model()

    response = model.invoke("Reply with the single word: pong")

    assert response.content.strip() != ""


@pytest.mark.bedrock
def test_structured_output_matches_schema() -> None:
    """Verify create_model()'s structured-output binding parses into the given schema."""
    model = BedrockLLM().create_model(_Greeting)

    result = model.invoke("Say hello in French. Respond with the language name and the greeting.")

    assert isinstance(result, _Greeting)
    assert result.greeting.strip() != ""


@pytest.mark.bedrock
def test_tool_bound_model_still_returns_text_for_an_unrelated_prompt() -> None:
    """Regression guard for the DeepSeek V3.x ChatBedrockConverse bug where
    binding any tool silently blocked the model from ever returning text."""
    model = BedrockLLM().create_raw_model().bind_tools([_get_capital])

    response = model.invoke("Reply with the single word: pong")

    assert response.tool_calls == []
    assert response.content.strip() != ""


@pytest.mark.bedrock
def test_tool_bound_model_calls_the_tool_when_forced() -> None:
    """Verify the model can actually emit a tool call at all — the bug
    langchain-aws fixed 2026-09-10 made DeepSeek V3.x structurally unable
    to. tool_choice="any" is used deliberately: in the default "auto" mode
    DeepSeek V3.1 sometimes narrates using a tool without calling it, which
    is real model behavior (ARCH/COUP's evidence hop is already optional-
    by-design for exactly this reason), not something this test asserts on."""
    model = BedrockLLM().create_raw_model().bind_tools([_get_capital], tool_choice="any")

    response = model.invoke("What is the capital of France? Use the _get_capital tool.")

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["name"] == "_get_capital"
    assert response.tool_calls[0]["args"] == {"country": "France"}


@pytest.mark.bedrock
def test_a_reply_cut_off_at_the_output_cap_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Bedrock's stop reason reaches the truncation check, so a cut-off reply fails
    instead of being parsed as data."""
    monkeypatch.setattr(get_settings(), "llm_max_output_tokens", 20)
    model = BedrockLLM().create_raw_model()

    with pytest.raises(OutputTruncatedError):
        model.invoke("Write a detailed ten-step guide to brewing coffee.")
