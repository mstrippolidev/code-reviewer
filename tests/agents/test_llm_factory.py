"""
    Tests for build_llm — which LLMInterface settings.llm_provider selects.
    Builds no chat model and calls no LLM.
"""
import pytest

from code_reviewer.agents.llm.bedrock import BedrockLLM
from code_reviewer.agents.llm.factory import build_llm
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings


@pytest.fixture
def set_llm_provider(monkeypatch: pytest.MonkeyPatch):
    def _set(provider: str) -> None:
        monkeypatch.setenv("LLM_PROVIDER", provider)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


def test_defaults_to_ollama() -> None:
    """Verify an unset LLM_PROVIDER falls back to local Ollama."""
    assert get_settings().llm_provider == "ollama"


def test_ollama_provider_builds_ollama_llm(set_llm_provider) -> None:
    set_llm_provider("ollama")

    assert isinstance(build_llm(), OllamaLLM)


def test_openrouter_provider_builds_openrouter(set_llm_provider) -> None:
    set_llm_provider("openrouter")

    assert isinstance(build_llm(), OpenRouter)


def test_bedrock_provider_builds_bedrock_llm(set_llm_provider) -> None:
    set_llm_provider("bedrock")

    assert isinstance(build_llm(), BedrockLLM)
