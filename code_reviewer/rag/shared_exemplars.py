"""
    The repo-less exemplar corpus: curated good code belonging to no repo and
    no owner, in its own table so a repo-scoped lookup can never reach it and
    it can never hold anything private.
"""
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)

from code_reviewer.rag.errors import VectorStoreQueryError
from code_reviewer.rag.exemplars import Exemplar, ExemplarSource, ExemplarStoreBase
from code_reviewer.schemas.review import CodeKey

SHARED_EXEMPLAR_TABLE_NAME = "shared_exemplar_embeddings"


@dataclass(frozen=True)
class SharedExemplarQuery:
    """One lookup against the repo-less corpus, carrying no repo or owner —
    there is nothing here to scope, which is what makes it readable from
    any review."""

    code_key: CodeKey
    code: str
    relevance_floor: float


class SharedExemplarStore(ExemplarStoreBase):
    """Keeps the repo-less corpus of curated good code, retrievable per principle."""

    def __init__(self, vector_store: Any = None, embedding: Any = None) -> None:
        super().__init__(vector_store, embedding, SHARED_EXEMPLAR_TABLE_NAME)

    def add_exemplar(self, code_key: CodeKey, source: ExemplarSource) -> None:
        """Add one piece of curated good code, visible to every review this
        system runs — only deliberately curated code belongs here.

        Raises:
            FileEmbeddingError: If splitting or embedding the code fails.
            VectorStoreWriteError: If writing the exemplar fails.
        """
        self._add(
            source,
            {
                "file_path": source.file_path,
                "code_key": code_key.value,
                "indexed_at": datetime.now(UTC),
            },
        )

    def is_empty(self) -> bool:
        """Whether the corpus holds nothing yet, so a caller can tell a
        first-time bootstrap from a corpus that is already curated.

        Raises:
            VectorStoreQueryError: If the lookup fails.
        """
        try:
            return not self._vector_store.get_nodes(filters=self._any_code_key_filter())
        except Exception as error:
            raise VectorStoreQueryError("Failed to inspect the shared exemplar corpus") from error

    def _any_code_key_filter(self) -> MetadataFilters:
        return MetadataFilters(
            filters=[
                MetadataFilter(
                    key="code_key",
                    operator=FilterOperator.IN,
                    value=[code_key.value for code_key in CodeKey],
                )
            ],
            condition=FilterCondition.AND,
        )

    def find_exemplars(self, query: SharedExemplarQuery, top_k: int = 3) -> list[Exemplar]:
        """Retrieve curated good code for one principle, unscoped by repo.

        Returns:
            Exemplars at or above the query's relevance floor, best first.

        Raises:
            VectorStoreQueryError: If querying the vector store fails.
        """
        filters = MetadataFilters(
            filters=[self._code_key_filter(query.code_key)], condition=FilterCondition.AND
        )
        return self._find(query, filters, top_k)
