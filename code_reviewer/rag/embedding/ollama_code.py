"""
    Code-specific embedding used for ollama
"""
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.ollama import OllamaEmbedding

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.base import EmbeddingInterface

settings = get_settings()

NOMIC_EMBED_CODE_DIM = 3584


class OllamaCodeEmbeddingProvider(EmbeddingInterface):
    """Builds the code-specific embedding client backed by a local Ollama instance."""

    def create_embedding_model(self) -> BaseEmbedding:
        """Ollama truncates an over-long input silently rather than raising,
        so num_ctx must exceed the largest text embedded on either side of a
        comparison."""
        return OllamaEmbedding(
            model_name=settings.ollama_code_embed_model,
            base_url=settings.ollama_base_url,
            ollama_additional_kwargs={"num_ctx": settings.ollama_embed_num_ctx},
        )

    @property
    def embed_dim(self) -> int:
        return NOMIC_EMBED_CODE_DIM
