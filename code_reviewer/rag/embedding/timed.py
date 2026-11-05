"""
    Times the synchronous embedding hooks every LlamaIndex embedding model implements, so every embedding
    the system performs is measured at the one place the providers build their clients.
"""
from code_reviewer.telemetry.rag_metrics import EmbeddingKind, rag_metrics


class TimedEmbeddingMixin:
    """Mixed in ahead of a LlamaIndex embedding model: each hook times the model's own implementation."""

    def _get_query_embedding(self, query: str) -> list[float]:
        with rag_metrics.track_embedding(EmbeddingKind.QUERY):
            return super()._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        with rag_metrics.track_embedding(EmbeddingKind.DOCUMENT):
            return super()._get_text_embedding(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        with rag_metrics.track_embedding(EmbeddingKind.DOCUMENT):
            return super()._get_text_embeddings(texts)
