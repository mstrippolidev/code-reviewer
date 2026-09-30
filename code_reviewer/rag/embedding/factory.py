"""
    Builds the EmbeddingInterface configured by settings.embedding_provider.
"""
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.base import EmbeddingInterface
from code_reviewer.rag.embedding.bedrock import BedrockEmbeddingProvider
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider

_PROVIDERS: dict[str, type[EmbeddingInterface]] = {
    "ollama": OllamaCodeEmbeddingProvider,
    "bedrock": BedrockEmbeddingProvider,
}


def build_embedding() -> EmbeddingInterface:
    return _PROVIDERS[get_settings().embedding_provider]()
