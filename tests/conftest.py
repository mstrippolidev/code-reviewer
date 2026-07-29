"""
    Shared fixtures for the test suite.
"""
import pytest

from code_reviewer.agents.llm.ollama import OllamaLLM

SMALL_TEST_MODEL = "qwen2.5-coder:7b"


class SmallOllamaLLM(OllamaLLM):
    """OllamaLLM pinned to a smaller local model for tests, instead of the
    heavier model configured in .env for production agent runs."""

    def _get_model_name(self) -> str:
        return SMALL_TEST_MODEL


@pytest.fixture(scope="session")
def small_llm() -> SmallOllamaLLM:
    """LLMInterface backed by a small local Ollama model, for tests that
    need a real LLM call rather than a mock."""
    return SmallOllamaLLM()
