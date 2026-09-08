"""
    Shared fixtures for the test suite.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.llm.ollama import OllamaLLM
from code_reviewer.agents.llm.openrouter import OpenRouter
from code_reviewer.config.settings import get_settings

SMALL_TEST_MODEL = "qwen2.5-coder:7b"


class SmallOllamaLLM(OllamaLLM):
    """OllamaLLM pinned to a smaller local model for tests, instead of the
    heavier model configured in .env for production agent runs."""

    def _get_model_name(self) -> str:
        return SMALL_TEST_MODEL


def _judge_models() -> list[str]:
    raw = get_settings().openrouter_judge_models
    return [model.strip() for model in raw.split(",") if model.strip()]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--llm-provider",
        default="ollama",
        choices=("ollama", "openrouter", "openrouter-multi"),
        help="Which LLM backend LLM-marked tests run against. Defaults to "
        "a small local Ollama model; 'openrouter' runs the same tests "
        "against the model configured by OPENROUTER_MODEL; "
        "'openrouter-multi' runs every LLM-marked test once per model in "
        "OPENROUTER_JUDGE_MODELS, for validating a prompt across several "
        "disjoint model families.",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Only 'openrouter-multi' fans small_llm out across several models —
    the default and 'openrouter' choices parametrize nothing, so every
    existing test run behaves exactly as before."""
    if "small_llm" not in metafunc.fixturenames:
        return
    if metafunc.config.getoption("--llm-provider") != "openrouter-multi":
        return
    models = _judge_models()
    metafunc.parametrize("small_llm", models, indirect=True, ids=models)


@pytest.fixture(scope="session")
def small_llm(request: pytest.FixtureRequest) -> LLMInterface:
    """LLMInterface for tests that need a real LLM call rather than a mock.

    Backend is chosen by --llm-provider (see pytest_addoption above):
    defaults to a small local Ollama model, OpenRouter's configured model
    for 'openrouter', or one OpenRouter model per OPENROUTER_JUDGE_MODELS
    entry for 'openrouter-multi' (see pytest_generate_tests above, which
    supplies request.param in that case).
    """
    provider = request.config.getoption("--llm-provider")
    if provider == "openrouter-multi":
        return OpenRouter(model_name=request.param)
    if provider == "openrouter":
        return OpenRouter()
    return SmallOllamaLLM()
