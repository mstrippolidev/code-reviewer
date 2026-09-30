"""
    Embedding used for AWS Bedrock
"""
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.bedrock import BedrockEmbedding

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.base import EmbeddingInterface

settings = get_settings()

TITAN_EMBED_TEXT_V2_MODEL = "amazon.titan-embed-text-v2:0"
TITAN_EMBED_TEXT_V2_DIM = 1024


class BedrockEmbeddingProvider(EmbeddingInterface):
    """Builds the embedding client backed by AWS Bedrock's Titan Text Embeddings V2."""

    def create_embedding_model(self) -> BaseEmbedding:
        return BedrockEmbedding(
            region_name=settings.bedrock_region,
            model_name=TITAN_EMBED_TEXT_V2_MODEL,
            additional_kwargs={"dimensions": TITAN_EMBED_TEXT_V2_DIM, "normalize": True},
        )

    @property
    def embed_dim(self) -> int:
        return TITAN_EMBED_TEXT_V2_DIM
