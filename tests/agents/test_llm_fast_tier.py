"""
    Tests for LLMInterface.for_fast_tier — which model a fast-tier caller
    ends up with, per provider. Builds no chat model and calls no LLM.
"""
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings


def test_openrouter_fast_tier_runs_the_configured_fast_model() -> None:
    """Verify a default OpenRouter swaps to OPENROUTER_FAST_MODEL for fast-tier calls."""
    fast_llm = OpenRouter().for_fast_tier()

    assert fast_llm._get_model_name() == get_settings().openrouter_fast_model


def test_openrouter_with_an_explicit_model_keeps_it_for_fast_tier_calls() -> None:
    """Verify a caller that named a model explicitly is never silently switched to another."""
    explicit_llm = OpenRouter(model_name="some/judge-model")

    assert explicit_llm.for_fast_tier() is explicit_llm


def test_only_the_configured_main_model_is_expected_to_send_reasoning() -> None:
    """Verify the main model is held to the reasoning check while the fast tier and explicit models are not."""
    assert OpenRouter().emits_reasoning
    assert not OpenRouter().for_fast_tier().emits_reasoning
    assert not OpenRouter(model_name="some/judge-model").emits_reasoning


def test_ollama_is_not_expected_to_send_reasoning() -> None:
    """Verify the local provider is left out of the reasoning check."""
    assert not OllamaLLM().emits_reasoning


def test_ollama_has_no_fast_tier_and_returns_itself() -> None:
    """Verify local Ollama, which has no fast model configured, keeps its own model."""
    ollama_llm = OllamaLLM()

    assert ollama_llm.for_fast_tier() is ollama_llm
