"""
    Shared fixtures for the test suite.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter

SMALL_TEST_MODEL = "qwen2.5-coder:7b"


class SmallOllamaLLM(OllamaLLM):
    """OllamaLLM pinned to a smaller local model for tests, instead of the
    heavier model configured in .env for production agent runs."""

    def _get_model_name(self) -> str:
        return SMALL_TEST_MODEL


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--llm-provider",
        default="ollama",
        choices=("ollama", "openrouter"),
        help="Which LLM backend LLM-marked tests run against. Defaults to "
        "a small local Ollama model; pass 'openrouter' to run the same "
        "tests against the model configured by OPENROUTER_MODEL instead.",
    )


@pytest.fixture(scope="session")
def small_llm(request: pytest.FixtureRequest) -> LLMInterface:
    """LLMInterface for tests that need a real LLM call rather than a mock.

    Backend is chosen by --llm-provider (see pytest_addoption above):
    defaults to a small local Ollama model, or OpenRouter's configured
    model when passed 'openrouter'.
    """
    if request.config.getoption("--llm-provider") == "openrouter":
        return OpenRouter()
    return SmallOllamaLLM()
