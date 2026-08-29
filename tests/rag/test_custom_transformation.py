"""
    Tests for ExplainedChunkSplitter: the raw code must survive in metadata
    for consumers that need real source (DRY, the ARCH/COUP evidence hop),
    but must never leak into what actually gets embedded.
"""
from llama_index.core import Document
from llama_index.core.schema import MetadataMode

from code_reviewer.rag.custom_transformation import ExplainedChunkSplitter

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"
EXPLANATION = "Adds two numbers and returns the sum."


class _FakeExplainer:
    """Fake in place of ChunkExplainer: returns a fixed explanation, so
    these tests stay fast and don't reach a real LLM."""

    def explain(self, code: str) -> str:
        return EXPLANATION


def _explain_document(content: str) -> list:
    document = Document(text=content, metadata={"file_path": "math_ops.py"})
    return ExplainedChunkSplitter(explainer=_FakeExplainer())([document])


def test_as_node_stores_the_raw_code_in_metadata() -> None:
    """Verify the original code survives untouched in metadata."""
    nodes = _explain_document(ADD_FUNCTION)

    assert nodes[0].metadata["code"].strip() == ADD_FUNCTION.strip()


def test_as_node_uses_the_explanation_as_the_node_text() -> None:
    """Verify the node's text is the explanation, not the raw code — that's
    what the embedding stage downstream actually embeds."""
    nodes = _explain_document(ADD_FUNCTION)

    assert nodes[0].text == EXPLANATION


def test_code_metadata_is_excluded_from_the_embedded_content() -> None:
    """Verify the raw code never reaches what gets embedded, even though
    it's readable via metadata — the entire point of keeping it out of
    `text` rather than concatenating it in."""
    nodes = _explain_document(ADD_FUNCTION)

    embedded_content = nodes[0].get_content(metadata_mode=MetadataMode.EMBED)

    assert "return a + b" not in embedded_content
