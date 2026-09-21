"""
    Tests for ChunkExplainer: a fake for error wrapping, a real LLM call for
    the happy path.
"""
import pytest

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.rag import chunk_explainer as chunk_explainer_module
from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.errors import ChunkExplanationError

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"


class _FakeLLMInterface(LLMInterface):
    """Minimal LLMInterface stand-in — create_raw_model is overridden so
    tests never touch a real provider's init_chat_model wiring."""

    def create_raw_model(self) -> None:
        return None

    def _get_model_name(self) -> str:
        return "fake-model"

    def _get_model_provider(self) -> str:
        return "fake"

    def _get_base_url(self) -> str:
        return "http://fake"

    def build_response_format(self, schema: type) -> type:
        return schema


class _FailingAgent:
    def invoke(self, messages: dict) -> dict:
        raise RuntimeError("boom")


def test_explain_raises_chunk_explanation_error_when_the_llm_call_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a failing LLM call surfaces as ChunkExplanationError, not a raw exception."""
    monkeypatch.setattr(chunk_explainer_module, "create_agent", lambda **kwargs: _FailingAgent())
    explainer = ChunkExplainer(llm=_FakeLLMInterface())

    with pytest.raises(ChunkExplanationError):
        explainer.explain(ADD_FUNCTION)


@pytest.mark.llm
def test_explain_returns_a_non_empty_explanation(small_llm) -> None:
    """Verify explain() produces real prose describing the code, not an empty or malformed result."""
    explainer = ChunkExplainer(llm=small_llm)

    explanation = explainer.explain(ADD_FUNCTION)

    assert len(explanation.strip()) > 0
