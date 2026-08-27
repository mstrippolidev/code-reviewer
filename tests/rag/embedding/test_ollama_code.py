"""
    Tests for OllamaCodeEmbeddingProvider: pure construction, no live Ollama call.
"""
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.ollama_code import (
    NOMIC_EMBED_CODE_DIM,
    OllamaCodeEmbeddingProvider,
)

settings = get_settings()


def test_ollama_code_embedding_provider_reports_nomic_embed_code_dimension() -> None:
    """Verify embed_dim matches nomic-embed-code's known output size, since
    PGVectorStore's vector column must be sized to exactly this.
    """
    provider = OllamaCodeEmbeddingProvider()

    assert provider.embed_dim == NOMIC_EMBED_CODE_DIM


def test_ollama_code_embedding_provider_builds_client_with_configured_model_name() -> None:
    """Verify the embedding client is wired to the model set in .env, not a
    hardcoded default that could silently diverge from configuration.
    """
    provider = OllamaCodeEmbeddingProvider()

    embedding_model = provider.create_embedding_model()

    assert embedding_model.model_name == settings.ollama_code_embed_model


def test_ollama_code_embedding_provider_builds_client_with_configured_base_url() -> None:
    """Verify the embedding client points at the Ollama instance set in
    .env, not a hardcoded default that could silently diverge.
    """
    provider = OllamaCodeEmbeddingProvider()

    embedding_model = provider.create_embedding_model()

    assert embedding_model.base_url == settings.ollama_base_url
