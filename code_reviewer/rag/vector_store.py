"""
    Create a instance of vector store object
"""
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy.engine import URL

from code_reviewer.config.settings import get_settings
from code_reviewer.rag.embedding.base import EmbeddingInterface
from code_reviewer.rag.embedding.ollama import OllamaEmbeddingProvider

settings = get_settings()


def build_connection_url(drivername: str) -> URL:
    """Build a connection URL via SQLAlchemy's URL object rather than a raw
    f-string, so reserved characters in the password (e.g. '@') are encoded
    correctly instead of corrupting the host/credential split.
    """
    return URL.create(
        drivername=drivername,
        username=settings.pg_user,
        password=settings.pg_password,
        host=settings.pg_host,
        port=settings.pg_port,
        database=settings.pg_database,
    )


def create_vector_store_instance(
    embedding: EmbeddingInterface | None = None,
    schema_name: str = "code_reviewer",
) -> PGVectorStore:
    """Build the PGVectorStore the RAG layer reads and writes through.

    Args:
        embedding: Provider whose embed_dim sizes the store's vector
            column. Defaults to the local Ollama provider.
        schema_name: Postgres schema to connect to. Defaults to the
            production "code_reviewer" schema; integration tests override
            this to an isolated schema so they never touch real data.

    Returns:
        A PGVectorStore connected to the given schema, with repo_id and
        owner_id indexed for tenant-scoped filtering.
    """
    embedding = embedding or OllamaEmbeddingProvider()
    return PGVectorStore.from_params(
        connection_string=build_connection_url("postgresql+psycopg2"),
        async_connection_string=build_connection_url("postgresql+asyncpg"),
        table_name="code_embeddings",
        schema_name=schema_name,
        embed_dim=embedding.embed_dim,
        indexed_metadata_keys={("repo_id", "text"), ("owner_id", "text")},
        use_jsonb=True,
    )