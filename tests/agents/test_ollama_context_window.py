"""
    Tests for OllamaLLM's context-window kwarg — which provider gets it and
    from where. Builds no chat model and calls no LLM.
"""
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings


def test_ollama_sizes_its_context_window_from_settings() -> None:
    """Verify every local Ollama call — agents and the guardrails intake
    screen alike — requests OLLAMA_LLM_NUM_CTX, not Ollama's own default,
    which is too small for a real prompt plus a real file's content."""
    kwargs = OllamaLLM()._get_extra_kwargs()

    assert kwargs["num_ctx"] == get_settings().ollama_llm_num_ctx


def test_openrouter_has_no_context_window_kwarg() -> None:
    """Verify a hosted provider is never handed an Ollama-only kwarg it would reject."""
    kwargs = OpenRouter()._get_extra_kwargs()

    assert "num_ctx" not in kwargs
