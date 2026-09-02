"""
    Tests for both chunk splitters: the raw code must survive in metadata
    for consumers that need real source (DRY, the ARCH/COUP evidence hop),
    and what reaches the embedder must be the chunk's text alone, since a
    query is embedded as bare text with no metadata of its own.
"""
from llama_index.core import Document
from llama_index.core.schema import MetadataMode

from code_reviewer.rag.custom_transformation import CodeChunkSplitter, ExplainedChunkSplitter

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"
EXPLANATION = "Adds two numbers and returns the sum."


class _FakeExplainer:
    """Fake in place of ChunkExplainer: returns a fixed explanation, so
    these tests stay fast and don't reach a real LLM."""

    def explain(self, code: str) -> str:
        return EXPLANATION


def _document(content: str) -> Document:
    return Document(text=content, metadata={"repo_id": "12345", "file_path": "math_ops.py"})


def _explain_document(content: str) -> list:
    return ExplainedChunkSplitter(explainer=_FakeExplainer())([_document(content)])


def _split_document(content: str) -> list:
    return CodeChunkSplitter()([_document(content)])


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


def test_explained_chunk_embeds_the_explanation_and_nothing_else() -> None:
    """Verify no metadata rides along into the vector. A stored chunk and a
    query must be embedded in the same representation, and a query carries
    no metadata at all."""
    nodes = _explain_document(ADD_FUNCTION)

    embedded_content = nodes[0].get_content(metadata_mode=MetadataMode.EMBED)

    assert embedded_content == EXPLANATION


def test_code_chunk_embeds_the_code_and_nothing_else() -> None:
    """Verify the exemplar corpora embed bare code, matching the bare code a
    retrieval query sends."""
    nodes = _split_document(ADD_FUNCTION)

    embedded_content = nodes[0].get_content(metadata_mode=MetadataMode.EMBED)

    assert embedded_content.strip() == ADD_FUNCTION.strip()


def test_bookkeeping_metadata_stays_available_for_filtering() -> None:
    """Verify excluding metadata from the embedding never removes it from
    the node, since every scope filter reads it back."""
    nodes = _split_document(ADD_FUNCTION)

    assert nodes[0].metadata["repo_id"] == "12345"
