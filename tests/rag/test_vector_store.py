"""
    Tests for create_vector_store_instance: pure wiring, plus integration
    checks against a real local Postgres.
"""
from collections.abc import Iterator

import pytest
import sqlalchemy
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.vector_stores.postgres import PGVectorStore

from code_reviewer.rag.embedding.base import EmbeddingInterface
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.vector_store import create_vector_store_instance


class FakeEmbeddingProvider(EmbeddingInterface):
    """Test double exposing a controllable embed_dim, since
    create_vector_store_instance never calls create_embedding_model().
    """

    def __init__(self, embed_dim: int) -> None:
        self._embed_dim = embed_dim

    def create_embedding_model(self) -> BaseEmbedding:
        raise NotImplementedError("vector_store wiring never embeds")

    @property
    def embed_dim(self) -> int:
        return self._embed_dim


@pytest.fixture
def initialized_vector_store() -> Iterator[PGVectorStore]:
    vector_store = create_vector_store_instance()

    vector_store.add([])

    yield vector_store

    # Only the sync engine is ever used in these tests, so only it needs
    # disposing — the async engine's dispose() requires greenlet, an
    # unneeded dependency for a connection that was never opened here.
    vector_store.client.dispose()


def test_create_vector_store_instance_uses_code_embeddings_table_name() -> None:
    """Verify the store targets the code_embeddings table, not a stray
    default name.
    """
    vector_store = create_vector_store_instance(FakeEmbeddingProvider(embed_dim=1))

    assert vector_store.table_name == "code_embeddings"


def test_create_vector_store_instance_uses_code_reviewer_schema() -> None:
    """Verify the store targets the code_reviewer schema created for this
    project, not Postgres's default public schema.
    """
    vector_store = create_vector_store_instance(FakeEmbeddingProvider(embed_dim=1))

    assert vector_store.schema_name == "code_reviewer"


def test_create_vector_store_instance_sizes_embedding_column_from_provider() -> None:
    """Verify the vector column's size tracks whatever embed_dim the
    embedding provider reports, so store and provider can never drift.
    """
    vector_store = create_vector_store_instance(FakeEmbeddingProvider(embed_dim=1234))

    assert vector_store.embed_dim == 1234


def test_create_vector_store_instance_indexes_repo_id_and_owner_id() -> None:
    """Verify repo_id and owner_id are indexed metadata keys, since they
    gate every tenant-scoped query and must never fall back to a scan.
    """
    vector_store = create_vector_store_instance(FakeEmbeddingProvider(embed_dim=1))

    assert vector_store.indexed_metadata_keys == {
        ("repo_id", "text"),
        ("owner_id", "text"),
    }


def test_create_vector_store_instance_defaults_to_ollama_code_embedding_provider() -> None:
    """Verify omitting the embedding argument falls back to the local
    code-embedding provider rather than requiring every caller to supply one.
    """
    vector_store = create_vector_store_instance()

    assert vector_store.embed_dim == OllamaCodeEmbeddingProvider().embed_dim


@pytest.mark.db
def test_create_vector_store_instance_creates_table_in_code_reviewer_schema(
    initialized_vector_store: PGVectorStore,
) -> None:
    """Verify the table is actually provisioned in Postgres, not just
    configured in Python — a wrong schema or a missing extension would
    only surface here, never from construction alone.
    """
    with initialized_vector_store.client.connect() as connection:
        table_exists = connection.execute(
            sqlalchemy.text(
                "SELECT to_regclass('code_reviewer.data_code_embeddings') IS NOT NULL"
            )
        ).scalar()

    assert table_exists is True


@pytest.mark.db
def test_create_vector_store_instance_creates_repo_id_index(
    initialized_vector_store: PGVectorStore,
) -> None:
    """Verify the repo_id index actually exists in Postgres, not just
    requested in indexed_metadata_keys — this is the difference between a
    fast tenant-scoped query and a full scan once real data exists.
    """
    with initialized_vector_store.client.connect() as connection:
        index_row = connection.execute(
            sqlalchemy.text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'code_reviewer' "
                "AND tablename = 'data_code_embeddings' AND indexname LIKE '%repo_id%'"
            )
        ).fetchone()

    assert index_row is not None
