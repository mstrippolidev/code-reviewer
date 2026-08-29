"""
    Custom transformation to wire up the RAG layer to the vector store.
"""
from typing import Any, Sequence

from llama_index.core.schema import BaseNode, TextNode, TransformComponent

from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.chunk_explainer import ChunkExplainer


class ExplainedChunkSplitter(TransformComponent):
    """Splits a document into per-function/class chunks, replacing each
    chunk's code with an LLM-generated explanation of its behavior.
    """

    def __init__(self, explainer: ChunkExplainer | None = None) -> None:
        super().__init__()
        self._explainer = explainer or ChunkExplainer()

    def __call__(self, nodes: Sequence[BaseNode], **kwargs: Any) -> list[BaseNode]:
        return [explained_node for node in nodes for explained_node in self._explain_node(node)]

    def _explain_node(self, node: BaseNode) -> list[TextNode]:
        chunks = PythonCodeSplit().split_code(node.get_content())
        return [self._as_node(node, chunk) for chunk in chunks]

    def _as_node(self, source: BaseNode, chunk: CodeChunk) -> TextNode:
        explanation = self._explainer.explain(chunk.code)
        return TextNode(
            text=explanation,
            metadata={
                **source.metadata,
                "chunk_name": chunk.name,
                "chunk_type": chunk.chunk_type,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "code": chunk.code,
            },
            excluded_embed_metadata_keys=["code"],
        )