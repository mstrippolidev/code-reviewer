"""
    Custom transformation to wire up the RAG layer to the vector store.
"""
from typing import Any, Sequence

from llama_index.core.schema import BaseNode, TextNode, TransformComponent

from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.chunk_explainer import ChunkExplainer


class ChunkSplitter(TransformComponent):
    """Splits a document into per-function/class chunks. Subclasses decide
    what text each chunk is embedded as, which is the whole difference
    between a corpus matched on behaviour and one matched on code."""

    def __call__(self, nodes: Sequence[BaseNode], **kwargs: Any) -> list[BaseNode]:
        return [chunk_node for node in nodes for chunk_node in self._split_node(node)]

    def _split_node(self, node: BaseNode) -> list[TextNode]:
        chunks = PythonCodeSplit().split_code(node.get_content())
        return [self._as_node(node, chunk) for chunk in chunks]

    def _chunk_metadata(self, source: BaseNode, chunk: CodeChunk) -> dict[str, Any]:
        return {
            **source.metadata,
            "chunk_name": chunk.name,
            "chunk_type": chunk.chunk_type,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
        }

    def _as_node(self, source: BaseNode, chunk: CodeChunk) -> TextNode:
        raise NotImplementedError


class CodeChunkSplitter(ChunkSplitter):
    """Embeds each chunk as the code itself, for a corpus where a match
    should follow the code's own shape."""

    def _as_node(self, source: BaseNode, chunk: CodeChunk) -> TextNode:
        return TextNode(text=chunk.code, metadata=self._chunk_metadata(source, chunk))


class ExplainedChunkSplitter(ChunkSplitter):
    """Embeds each chunk as an LLM explanation of its behavior, so two
    chunks doing the same thing in different syntax still match."""

    def __init__(self, explainer: ChunkExplainer | None = None) -> None:
        super().__init__()
        self._explainer = explainer or ChunkExplainer()

    def _as_node(self, source: BaseNode, chunk: CodeChunk) -> TextNode:
        return TextNode(
            text=self._explainer.explain(chunk.code),
            metadata={**self._chunk_metadata(source, chunk), "code": chunk.code},
            excluded_embed_metadata_keys=["code"],
        )
