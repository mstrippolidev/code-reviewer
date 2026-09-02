"""
    Tests for the repo-less exemplar corpus: what it writes, and how it
    reports emptiness. The vector store and the embedding are faked, so no
    Postgres or Ollama call happens here.
"""
from typing import Any

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import MetadataFilters

from code_reviewer.rag.embedding.base import EmbeddingInterface
from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.exemplars import ExemplarSource
from code_reviewer.rag.shared_exemplars import SharedExemplarStore
from code_reviewer.schemas.review import CodeKey

CURATED_CODE = "class InvoiceTotals:\n    def total(self) -> int:\n        return 0\n"


class FakeEmbedding(BaseEmbedding):
    def _get_query_embedding(self, query: str) -> list[float]:
        return [0.1, 0.2]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return [0.1, 0.2]

    def _get_text_embedding(self, text: str) -> list[float]:
        return [0.1, 0.2]


class FakeEmbeddingProvider(EmbeddingInterface):
    def create_embedding_model(self) -> BaseEmbedding:
        return FakeEmbedding()

    @property
    def embed_dim(self) -> int:
        return 2


class FakeVectorStore:
    """Stand-in for PGVectorStore. get_nodes rejects a call carrying neither
    node ids nor filters, exactly as the real store's own assertion does."""

    def __init__(self, nodes: list[BaseNode] | None = None) -> None:
        self.nodes: list[BaseNode] = nodes or []

    def add(self, nodes: list[BaseNode]) -> list[str]:
        self.nodes.extend(nodes)
        return [node.node_id for node in nodes]

    def get_nodes(
        self, node_ids: list[str] | None = None, filters: MetadataFilters | None = None
    ) -> list[BaseNode]:
        if node_ids is None and filters is None:
            raise AssertionError("Either node_ids or filters must be provided")
        return list(self.nodes)


def _store(vector_store: Any) -> SharedExemplarStore:
    return SharedExemplarStore(vector_store=vector_store, embedding=FakeEmbeddingProvider())


def test_add_exemplar_writes_the_curated_code_to_the_corpus() -> None:
    """Verify a curated entry reaches the vector store, exercising the whole
    embed-and-store path the repo-less corpus inherits."""
    vector_store = FakeVectorStore()

    _store(vector_store).add_exemplar(CodeKey.SOLID1, ExemplarSource("invoice.py", CURATED_CODE))

    assert len(vector_store.nodes) == 1


def test_add_exemplar_tags_the_chunk_with_its_principle() -> None:
    """Verify the stored chunk carries its code_key, since retrieval filters
    on it and an untagged entry could never be found again."""
    vector_store = FakeVectorStore()

    _store(vector_store).add_exemplar(CodeKey.COH, ExemplarSource("invoice.py", CURATED_CODE))

    assert vector_store.nodes[0].metadata["code_key"] == "COH"


def test_stored_chunks_carry_no_repo_or_owner() -> None:
    """Verify the repo-less corpus stores nothing scopable, which is what
    lets any review read it without reaching another owner's code."""
    vector_store = FakeVectorStore()

    _store(vector_store).add_exemplar(CodeKey.SOLID1, ExemplarSource("invoice.py", CURATED_CODE))

    assert not {"repo_id", "owner_id"} & set(vector_store.nodes[0].metadata)


def test_is_empty_is_true_for_a_corpus_holding_nothing() -> None:
    """Verify a first-time bootstrap is distinguishable from a populated
    corpus, since seeding only ever runs against an empty one."""
    assert _store(FakeVectorStore()).is_empty() is True


def test_is_empty_is_false_once_a_curated_entry_exists() -> None:
    """Verify a populated corpus reports itself as such, so fixture seeding
    never appends to hand-curated entries."""
    store = _store(FakeVectorStore())
    store.add_exemplar(CodeKey.SOLID1, ExemplarSource("invoice.py", CURATED_CODE))

    assert store.is_empty() is False


def test_is_empty_reports_a_store_outage_as_a_query_error() -> None:
    """Verify a failing lookup raises rather than reporting an empty corpus,
    which would let seeding overwrite curated entries it could not read."""
    class FailingVectorStore(FakeVectorStore):
        def get_nodes(self, node_ids: Any = None, filters: Any = None) -> list[BaseNode]:
            raise RuntimeError("connection refused")

    with pytest.raises(VectorStoreQueryError):
        _store(FailingVectorStore()).is_empty()
