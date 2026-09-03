"""
    Keeps one repo's indexed code corpus queryable by raw code — a second
    bucket beside LlamaIndexRagManager's explanation-based index. Two
    tables rather than one shared table queried asymmetrically: this keeps
    a stray query/document prefix mismatch from silently degrading one of
    the two lookups (see rag/embedding/ollama_code.py, which applies no
    prefix on either side today).

    Two independent recall routes read this same stored code: a dense
    vector search (catches near-misses whose LLM-written explanations
    diverged in wording) and a BM25 keyword search (catches copy-paste
    with light edits, via shared identifiers and calls). Both feed
    CrossHistoryDuplicateFinder as separate buckets, never fused by score
    — the downstream cross-encoder re-ranker scores the real code pairs
    anyway, so retrieval here only has to be a recall net.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.schema import BaseNode
from llama_index.core.vector_stores import FilterCondition, MetadataFilter, MetadataFilters
from llama_index.core.vector_stores.types import BasePydanticVectorStore
from llama_index.retrievers.bm25 import BM25Retriever

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

logger = logging.getLogger(__name__)

CODE_EMBEDDINGS_TABLE = "code_raw_embeddings"


class _DocumentPipeline(Protocol):
    """Contract for whatever splits and embeds documents into storable nodes."""

    def run(self, documents: list[Document]) -> list[BaseNode]: ...


@dataclass
class CodeMatch:
    """One indexed chunk returned by a raw-code dense similarity search."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    code: str
    score: float


@dataclass
class LexicalMatch:
    """One indexed chunk returned by a BM25 keyword-overlap search over the
    same stored code — a different candidate list, kept as its own type
    since its confidence signal (shared vocabulary) differs from a dense
    match's (embedding distance)."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    code: str
    score: float


class CodeSimilarityIndex:
    """Keeps one repo's indexed chunks queryable by raw code, embedded a
    second way beside LlamaIndexRagManager's explanation index — the same
    corpus, so a duplicate whose auto-generated explanation diverged in
    wording can still be found by how the code itself reads.
    """

    def __init__(
        self,
        vector_store: BasePydanticVectorStore | None = None,
        embedding: EmbeddingInterface | None = None,
        pipeline: _DocumentPipeline | None = None,
    ) -> None:
        self._embedding = embedding or OllamaCodeEmbeddingProvider()
        self._vector_store = vector_store or create_vector_store_instance(
            embedding=self._embedding, table_name=CODE_EMBEDDINGS_TABLE
        )
        self._pipeline = pipeline or self._build_default_pipeline()
        self._index: VectorStoreIndex | None = None

    def _get_index(self) -> VectorStoreIndex:
        if self._index is None:
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=self._vector_store,
                embed_model=self._embedding.create_embedding_model(),
            )
        return self._index

    def _build_default_pipeline(self) -> IngestionPipeline:
        """Build the real split-and-embed pipeline used outside of tests."""
        return IngestionPipeline(transformations=[CodeChunkSplitter(), self._embedding.create_embedding_model()])

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        """Replace one file's indexed chunks with freshly embedded ones from its current content.

        Raises:
            RepoOwnerRequiredError: If repo_data has no owner_id.
            FileEmbeddingError: If splitting or embedding the content fails.
            VectorStoreDeletionError: If removing the file's existing chunks fails.
            VectorStoreWriteError: If writing the new chunks fails.
        """
        if repo_data.owner_id is None:
            raise RepoOwnerRequiredError(
                f"Repo {repo_data.repo_id!r} has no owner_id — required before indexing its content."
            )

        document = Document(text=content, metadata=self._file_metadata(repo_data, file_path))
        nodes = self._embed_document(document)
        self.delete_file(repo_data.repo_id, file_path)
        self._store_nodes(nodes)

    def _file_metadata(self, repo_data: RepoData, file_path: str) -> dict[str, Any]:
        return {
            "repo_id": repo_data.repo_id,
            "owner_id": repo_data.owner_id,
            "file_path": file_path,
            "commit_sha": repo_data.commit_sha,
            "indexed_at": datetime.now(UTC),
        }

    def _embed_document(self, document: Document) -> list[BaseNode]:
        """Raises:
        FileEmbeddingError: If the pipeline fails.
        """
        try:
            return self._pipeline.run(documents=[document])
        except Exception as error:
            logger.exception("Failed to split and embed %s", document.metadata["file_path"])
            raise FileEmbeddingError(f"Could not split and embed {document.metadata['file_path']!r}") from error

    def _store_nodes(self, nodes: list[BaseNode]) -> None:
        """Raises:
        VectorStoreWriteError: If the write fails.
        """
        try:
            self._vector_store.add(nodes)
        except Exception as error:
            logger.exception("Failed to write %d raw-code chunk(s) to the vector store", len(nodes))
            raise VectorStoreWriteError("Failed to write embedded chunks to the vector store") from error

    def delete_file(self, repo_id: str, file_path: str) -> None:
        """Raises:
        VectorStoreDeletionError: If the delete itself fails.
        """
        try:
            self._vector_store.delete_nodes(filters=self._scope_filters(repo_id, file_path))
        except Exception as error:
            logger.exception("Failed to delete existing chunks for %r in repo %r", file_path, repo_id)
            raise VectorStoreDeletionError(f"Failed to delete existing chunks for {file_path!r}") from error

    def delete_repo(self, repo_id: str) -> None:
        """Raises:
        VectorStoreDeletionError: If the delete itself fails.
        """
        try:
            self._vector_store.delete_nodes(filters=self._scope_filters(repo_id))
        except Exception as error:
            logger.exception("Failed to delete all chunks for repo %r", repo_id)
            raise VectorStoreDeletionError(f"Failed to delete chunks for repo {repo_id!r}") from error

    def _scope_filters(
        self, repo_id: str, file_path: str | None = None, owner_id: str | None = None
    ) -> MetadataFilters:
        filters = [MetadataFilter(key="repo_id", value=repo_id)]
        if file_path:
            filters.append(MetadataFilter(key="file_path", value=file_path))
        if owner_id:
            filters.append(MetadataFilter(key="owner_id", value=owner_id))
        return MetadataFilters(filters=filters, condition=FilterCondition.AND)

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[CodeMatch]:
        """Find the top_k indexed chunks whose raw code is most similar to
        code, scoped to repo_data's repo/owner.

        Queried directly with code — symmetric, no explanation step, since
        every chunk in this index was embedded as code on both sides.

        Raises:
            VectorStoreQueryError: If querying the vector store fails.
        """
        retriever = self._get_index().as_retriever(
            similarity_top_k=top_k,
            filters=self._scope_filters(repo_data.repo_id, owner_id=repo_data.owner_id),
        )
        try:
            nodes = retriever.retrieve(code)
        except Exception as error:
            logger.exception("Raw-code similarity search failed for repo %r", repo_data.repo_id)
            raise VectorStoreQueryError(f"Raw-code similarity search failed for repo {repo_data.repo_id!r}") from error

        return [self._as_code_match(node.node, node.get_score()) for node in nodes]

    def find_lexical_matches(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[LexicalMatch]:
        """Find the top_k indexed chunks sharing the most distinctive
        vocabulary with code (BM25), scoped to repo_data's repo/owner.

        Builds the BM25 index fresh from this repo's already-stored nodes
        on every call rather than persisting one: a repo's corpus tops out
        at a few thousand chunks, well within what bm25s indexes in memory
        in milliseconds, so there is no scale here to justify a persistent
        second copy of the same content.

        Raises:
            VectorStoreQueryError: If fetching this repo's nodes fails.
        """
        nodes = self._repo_nodes(repo_data)
        if not nodes:
            return []
        retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k)
        results = retriever.retrieve(code)
        return [self._as_lexical_match(result.node, result.get_score()) for result in results]

    def _repo_nodes(self, repo_data: RepoData) -> list[BaseNode]:
        try:
            return self._vector_store.get_nodes(
                filters=self._scope_filters(repo_data.repo_id, owner_id=repo_data.owner_id)
            )
        except Exception as error:
            logger.exception("Failed to fetch indexed nodes for repo %r", repo_data.repo_id)
            raise VectorStoreQueryError(f"Failed to fetch indexed nodes for repo {repo_data.repo_id!r}") from error

    def _as_code_match(self, node: BaseNode, score: float) -> CodeMatch:
        return CodeMatch(
            file_path=node.metadata["file_path"],
            chunk_name=node.metadata["chunk_name"],
            start_line=node.metadata["start_line"],
            end_line=node.metadata["end_line"],
            code=node.get_content(),
            score=score,
        )

    def _as_lexical_match(self, node: BaseNode, score: float) -> LexicalMatch:
        return LexicalMatch(
            file_path=node.metadata["file_path"],
            chunk_name=node.metadata["chunk_name"],
            start_line=node.metadata["start_line"],
            end_line=node.metadata["end_line"],
            code=node.get_content(),
            score=score,
        )
