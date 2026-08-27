"""
    Tests for ChunkExplainer: a fake for error wrapping, a real LLM call for
    the happy path.
"""
import pytest
from langchain_core.runnables import Runnable, RunnableLambda

from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.errors import ChunkExplanationError
from code_reviewer.schemas.chunk_explanation import ChunkExplanation

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"


def _raise_runtime_error(_: dict) -> ChunkExplanation:
    raise RuntimeError("boom")


class _FailingLLM:
    """Fake LLMInterface whose model always raises, to test error wrapping without a live call."""

    def create_model(self, schema: type) -> Runnable:
        return RunnableLambda(_raise_runtime_error)


def test_explain_raises_chunk_explanation_error_when_the_llm_call_fails() -> None:
    """Verify a failing LLM call surfaces as ChunkExplanationError, not a raw exception."""
    explainer = ChunkExplainer(llm=_FailingLLM())

    with pytest.raises(ChunkExplanationError):
        explainer.explain(ADD_FUNCTION)


@pytest.mark.llm
def test_explain_returns_a_non_empty_explanation(small_llm) -> None:
    """Verify explain() produces real prose describing the code, not an empty or malformed result."""
    explainer = ChunkExplainer(llm=small_llm)

    explanation = explainer.explain(ADD_FUNCTION)

    assert len(explanation.strip()) > 0
