"""
    Tests for build_embedding — which EmbeddingInterface
    settings.embedding_provider selects. Builds no embedding client.
"""
import pytest

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.bedrock import BedrockEmbeddingProvider
from code_reviewer.rag.embedding.factory import build_embedding
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider


@pytest.fixture
def set_embedding_provider(monkeypatch: pytest.MonkeyPatch):
    def _set(provider: str) -> None:
        monkeypatch.setenv("EMBEDDING_PROVIDER", provider)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


def test_defaults_to_ollama() -> None:
    """Verify an unset EMBEDDING_PROVIDER falls back to local Ollama."""
    assert get_settings().embedding_provider == "ollama"


def test_ollama_provider_builds_ollama_code_embedding(set_embedding_provider) -> None:
    set_embedding_provider("ollama")

    assert isinstance(build_embedding(), OllamaCodeEmbeddingProvider)


def test_bedrock_provider_builds_bedrock_embedding(set_embedding_provider) -> None:
    set_embedding_provider("bedrock")

    assert isinstance(build_embedding(), BedrockEmbeddingProvider)
