"""
    Embedding used for ollama
"""
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.ollama import OllamaEmbedding

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.base import EmbeddingInterface

settings = get_settings()

NOMIC_EMBED_TEXT_DIM = 768


class OllamaEmbeddingProvider(EmbeddingInterface):
    """Builds the embedding client backed by a local Ollama instance."""

    def create_embedding_model(self) -> BaseEmbedding:
        return OllamaEmbedding(
            model_name=settings.ollama_embed_model,
            base_url=settings.ollama_base_url,
        )

    @property
    def embed_dim(self) -> int:
        return NOMIC_EMBED_TEXT_DIM
