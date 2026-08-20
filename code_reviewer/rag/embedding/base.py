"""
    Contract for building the embedding client every RAG module depends on.
"""
from abc import ABC, abstractmethod

from llama_index.core.base.embeddings.base import BaseEmbedding


class EmbeddingInterface(ABC):
    """Every RAG module (vector store, indexer, retriever) builds its
    embedding client through this interface rather than constructing one
    itself. Insert-time and query-time embeddings must come from the exact
    same client, or DRY silently compares vectors that were never
    comparable, with no error to signal it.
    """

    @abstractmethod
    def create_embedding_model(self) -> BaseEmbedding:
        """Build the embedding client."""

    @property
    @abstractmethod
    def embed_dim(self) -> int:
        """Output vector size of this embedding model. PGVectorStore's
        embed_dim must match this exactly, or the table's vector column
        won't accept what this client actually produces."""
