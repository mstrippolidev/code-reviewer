"""
    Stores and retrieves the exemplar corpus: known-good code kept per repo
    and per principle, retrieved as few-shot context at review time.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import FilterCondition, MetadataFilter, MetadataFilters
from llama_index.core.vector_stores.types import BasePydanticVectorStore

from code_reviewer.rag.custom_transformation import CodeChunkSplitter
from code_reviewer.rag.embedding.base import EmbeddingInterface
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.errors import (
    FileEmbeddingError,
    RepoOwnerRequiredError,
    VectorStoreDeletionError,
    VectorStoreQueryError,
    VectorStoreWriteError,
)
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.vector_store import create_vector_store_instance
from code_reviewer.schemas.review import CodeKey

logger = logging.getLogger(__name__)

EXEMPLAR_TABLE_NAME = "exemplar_embeddings"


@dataclass(frozen=True)
class Exemplar:
    """One retrieved piece of known-good code, with the score that let it through."""

    code_key: CodeKey
    file_path: str
    chunk_name: str
    code: str
    score: float


class ExemplarStoreBase:
    """Shared embedding and retrieval machinery for a corpus of known-good
    code. Each subclass owns its own table and its own scoping filters, so
    no query can reach a corpus other than the one it was built for."""

    def __init__(
        self,
        vector_store: BasePydanticVectorStore | None = None,
        embedding: EmbeddingInterface | None = None,
        table_name: str = EXEMPLAR_TABLE_NAME,
    ) -> None:
        self._embedding = embedding or OllamaCodeEmbeddingProvider()
        self._vector_store = vector_store or create_vector_store_instance(
            embedding=self._embedding, table_name=table_name
        )
        self._pipeline = IngestionPipeline(
            transformations=[CodeChunkSplitter(), self._embedding.create_embedding_model()]
        )
        self._index: VectorStoreIndex | None = None

    def _add(self, source: "ExemplarSource", metadata: dict[str, Any]) -> None:
        """Raises:
            FileEmbeddingError: If splitting or embedding the code fails.
            VectorStoreWriteError: If writing the exemplar fails.
        """
        self._store_nodes(self._embed_document(Document(text=source.code, metadata=metadata)))

    def _find(self, query: Any, filters: MetadataFilters, top_k: int) -> list[Exemplar]:
        """Raises:
            VectorStoreQueryError: If querying the vector store fails.
        """
        retriever = self._get_index().as_retriever(similarity_top_k=top_k, filters=filters)
        try:
            nodes = retriever.retrieve(query.code)
        except Exception as error:
            logger.exception("Exemplar search failed")
            raise VectorStoreQueryError("Exemplar search failed") from error
        found = [self._as_exemplar(node) for node in nodes]
        return [exemplar for exemplar in found if exemplar.score >= query.relevance_floor]

    def _code_key_filter(self, code_key: CodeKey) -> MetadataFilter:
        return MetadataFilter(key="code_key", value=code_key.value)


class ExemplarStore(ExemplarStoreBase):
    """Keeps one repo's corpus of known-good code, retrievable per principle."""

    def add_exemplar(self, repo_data: RepoData, code_key: CodeKey, source: "ExemplarSource") -> None:
        """Add one piece of known-good code to the corpus.

        Args:
            repo_data: Repo and owner this exemplar belongs to.
            code_key: The principle this code demonstrates well. Retrieval
                filters on it, so a SOLID1 exemplar never reaches SOLID2.
            source: The code and the path it came from.

        Raises:
            RepoOwnerRequiredError: If repo_data has no owner_id.
            FileEmbeddingError: If splitting or embedding the code fails.
            VectorStoreWriteError: If writing the exemplar fails.
        """
        if repo_data.owner_id is None:
            raise RepoOwnerRequiredError(
                f"Repo {repo_data.repo_id!r} has no owner_id — required before storing exemplars."
            )
        self._add(source, self._exemplar_metadata(repo_data, code_key, source.file_path))

    def _exemplar_metadata(
        self, repo_data: RepoData, code_key: CodeKey, file_path: str
    ) -> dict[str, Any]:
        return {
            "repo_id": repo_data.repo_id,
            "owner_id": repo_data.owner_id,
            "file_path": file_path,
            "code_key": code_key.value,
            "commit_sha": repo_data.commit_sha,
            "indexed_at": datetime.now(UTC),
        }

    def _embed_document(self, document: Document) -> list[BaseNode]:
        try:
            return self._pipeline.run(documents=[document])
        except Exception as error:
            logger.exception("Failed to embed exemplar from %s", document.metadata["file_path"])
            raise FileEmbeddingError(
                f"Could not embed exemplar from {document.metadata['file_path']!r}"
            ) from error

    def _store_nodes(self, nodes: list[BaseNode]) -> None:
        try:
            self._vector_store.add(nodes)
        except Exception as error:
            logger.exception("Failed to write %d exemplar chunk(s)", len(nodes))
            raise VectorStoreWriteError("Failed to write exemplar chunks to the vector store") from error

    def find_exemplars(self, query: "ExemplarQuery", top_k: int = 3) -> list[Exemplar]:
        """Retrieve the most similar known-good code for one principle.

        The query is the code itself, matching how every exemplar was
        stored. No behavioural rewrite stands between them: unlike DRY,
        which must match differently-written code doing the same thing, an
        exemplar lookup wants code shaped like what is being reviewed, and
        the corpus is scoped to one repo where framework vocabulary is
        shared rather than something to see past.

        Args:
            query: The code under review, its principle, and the relevance
                floor below which nothing is worth injecting.
            top_k: How many exemplars to retrieve at most.

        Returns:
            Exemplars at or above the relevance floor, best first. Empty
            when nothing clears it — an unrelated exemplar steers an agent's
            judgment worse than no exemplar at all.

        Raises:
            VectorStoreQueryError: If querying the vector store fails.
        """
        return self._find(query, self._scope_filters(query.repo_data, query.code_key), top_k)

    def _as_exemplar(self, node: Any) -> Exemplar:
        return Exemplar(
            code_key=CodeKey(node.node.metadata["code_key"]),
            file_path=node.node.metadata["file_path"],
            chunk_name=node.node.metadata["chunk_name"],
            code=node.node.get_content(),
            score=node.get_score(),
        )

    def _get_index(self) -> VectorStoreIndex:
        if self._index is None:
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=self._vector_store,
                embed_model=self._embedding.create_embedding_model(),
            )
        return self._index

    def _scope_filters(self, repo_data: RepoData, code_key: CodeKey) -> MetadataFilters:
        """Every exemplar is stored with an owner_id, so a lookup without one
        is a caller bug rather than a broader search — scoping it to repo_id
        alone would return a co-owner's exemplars for a shared public repo.

        Raises:
            RepoOwnerRequiredError: If repo_data has no owner_id.
        """
        if repo_data.owner_id is None:
            raise RepoOwnerRequiredError(
                f"Repo {repo_data.repo_id!r} has no owner_id — required before retrieving exemplars."
            )
        filters = [
            MetadataFilter(key="repo_id", value=repo_data.repo_id),
            MetadataFilter(key="owner_id", value=repo_data.owner_id),
            self._code_key_filter(code_key),
        ]
        return MetadataFilters(filters=filters, condition=FilterCondition.AND)

    def delete_repo(self, repo_id: str) -> None:
        """Remove every exemplar for a repo. A no-op if none exist yet.

        Raises:
            VectorStoreDeletionError: If the delete itself fails.
        """
        filters = MetadataFilters(
            filters=[MetadataFilter(key="repo_id", value=repo_id)], condition=FilterCondition.AND
        )
        try:
            self._vector_store.delete_nodes(filters=filters)
        except Exception as error:
            logger.exception("Failed to delete exemplars for repo %r", repo_id)
            raise VectorStoreDeletionError(f"Failed to delete exemplars for repo {repo_id!r}") from error


@dataclass(frozen=True)
class ExemplarSource:
    """The code being added to the corpus, and where it came from."""

    file_path: str
    code: str


@dataclass(frozen=True)
class ExemplarQuery:
    """One exemplar lookup: what is being reviewed, for which principle, and
    how relevant a match has to be before it is worth injecting."""

    repo_data: RepoData
    code_key: CodeKey
    code: str
    relevance_floor: float
