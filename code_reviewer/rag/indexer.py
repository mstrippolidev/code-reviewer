"""
    Keeps one repo's indexed code corpus in sync with LlamaIndex + pgvector.
    Owns every embedding in the system, at both index time and query time:
    callers pass raw code in and out, and never handle a vector or an
    explanation themselves.
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

from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.custom_transformation import ExplainedChunkSplitter
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


class _DocumentPipeline(Protocol):
    """Contract for whatever splits and embeds documents into storable nodes."""

    def run(self, documents: list[Document]) -> list[BaseNode]: ...


@dataclass
class SimilarChunk:
    """One indexed chunk returned by find_similar."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    text: str
    score: float
    code: str


@dataclass
class FileChunk:
    """One indexed chunk of a specific file, from get_file_chunks' exact
    lookup rather than a similarity search — so it carries no score."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    text: str
    code: str


class LlamaIndexRagManager:
    """Keeps one repo's indexed code corpus in sync with its current file content."""

    def __init__(
        self,
        vector_store: BasePydanticVectorStore | None = None,
        embedding: EmbeddingInterface | None = None,
        explainer: ChunkExplainer | None = None,
        pipeline: _DocumentPipeline | None = None,
    ) -> None:
        self._embedding = embedding or OllamaCodeEmbeddingProvider()
        self._explainer = explainer or ChunkExplainer()
        self._vector_store = vector_store or create_vector_store_instance(embedding=self._embedding)
        self._pipeline = pipeline or self._build_default_pipeline()
        self._index: VectorStoreIndex | None = None

    def _get_index(self) -> VectorStoreIndex:
        """Build the retrieval-side VectorStoreIndex on first.
        """
        if self._index is None:
            self._index = VectorStoreIndex.from_vector_store(
                vector_store=self._vector_store,
                embed_model=self._embedding.create_embedding_model(),
            )
        return self._index

    def _build_default_pipeline(self) -> IngestionPipeline:
        """Build the real split-and-embed pipeline used outside of tests."""
        explained_chunk_splitter = ExplainedChunkSplitter(self._explainer)
        return IngestionPipeline(transformations=[explained_chunk_splitter, self._embedding.create_embedding_model()])

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
        """Metadata every chunk of this file must carry to stay scoped and traceable."""
        return {
            "repo_id": repo_data.repo_id,
            "owner_id": repo_data.owner_id,
            "file_path": file_path,
            "commit_sha": repo_data.commit_sha,
            "indexed_at": datetime.now(UTC),
        }

    def _embed_document(self, document: Document) -> list[BaseNode]:
        """Split and embed one document.

        Raises:
            FileEmbeddingError: If the pipeline fails.
        """
        try:
            return self._pipeline.run(documents=[document])
        except Exception as error:
            logger.exception("Failed to split and embed %s", document.metadata["file_path"])
            raise FileEmbeddingError(
                f"Could not split and embed {document.metadata['file_path']!r}"
            ) from error

    def _store_nodes(self, nodes: list[BaseNode]) -> None:
        """Write already-embedded nodes to the vector store.

        Raises:
            VectorStoreWriteError: If the write fails.
        """
        try:
            self._vector_store.add(nodes)
        except Exception as error:
            logger.exception("Failed to write %d embedded chunk(s) to the vector store", len(nodes))
            raise VectorStoreWriteError("Failed to write embedded chunks to the vector store") from error

    def delete_file(self, repo_id: str, file_path: str) -> None:
        """Remove every indexed chunk for one file. A no-op if none exist yet.

        Raises:
            VectorStoreDeletionError: If the delete itself fails.
        """
        try:
            self._vector_store.delete_nodes(filters=self._scope_filters(repo_id, file_path))
        except Exception as error:
            logger.exception("Failed to delete existing chunks for %r in repo %r", file_path, repo_id)
            raise VectorStoreDeletionError(f"Failed to delete existing chunks for {file_path!r}") from error

    def _scope_filters(
        self, repo_id: str, file_path: str | None = None, owner_id: str | None = None
    ) -> MetadataFilters:
        """Build the repo_id filter every scoped operation uses, narrowed by
        file_path and/or owner_id when given.
        """
        filters = [MetadataFilter(key="repo_id", value=repo_id)]
        if file_path:
            filters.append(MetadataFilter(key="file_path", value=file_path))
        if owner_id:
            filters.append(MetadataFilter(key='owner_id', value=owner_id))

        return MetadataFilters(filters=filters, condition=FilterCondition.AND)

    def delete_repo(self, repo_id: str) -> None:
        """Remove every indexed chunk for a repo. A no-op if none exist yet.

        Raises:
            VectorStoreDeletionError: If the delete itself fails.
        """
        try:
            self._vector_store.delete_nodes(filters=self._scope_filters(repo_id))
        except Exception as error:
            logger.exception("Failed to delete all chunks for repo %r", repo_id)
            raise VectorStoreDeletionError(f"Failed to delete chunks for repo {repo_id!r}") from error

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        """Find the top_k indexed chunks whose behavior is most similar to
        code, scoped to repo_data's repo/owner.

        code is explained before embedding, since every indexed chunk was
        embedded as an explanation rather than as raw code — embedding code
        directly here would compare it against explanations in a shared
        vector space neither representation was meant to occupy alone.

        Raises:
            ChunkExplanationError: If explaining code fails.
            VectorStoreQueryError: If querying the vector store fails.
        """
        explanation = self._explainer.explain(code)
        retriever = self._get_index().as_retriever(
            similarity_top_k=top_k,
            filters=self._scope_filters(repo_data.repo_id, owner_id=repo_data.owner_id),
        )
        try:
            nodes = retriever.retrieve(explanation)
        except Exception as error:
            logger.exception("Similarity search failed for repo %r", repo_data.repo_id)
            raise VectorStoreQueryError(f"Similarity search failed for repo {repo_data.repo_id!r}") from error

        return [
            SimilarChunk(
                file_path=node.node.metadata["file_path"],
                chunk_name=node.node.metadata["chunk_name"],
                start_line=node.node.metadata["start_line"],
                end_line=node.node.metadata["end_line"],
                text=node.node.get_content(),
                score=node.get_score(),
                code=node.node.metadata.get("code", ""),
            )
            for node in nodes
        ]

    def get_file_chunks(self, repo_id: str, owner_id: str | None, file_path: str) -> list[FileChunk]:
        """Exact lookup of one file's indexed content, for the multi-hop
        evidence pass. Not a similarity search — the caller already knows
        precisely which file it needs to read, so this filters the vector
        store's metadata directly instead of running it through the ANN index.

        Raises:
            VectorStoreQueryError: If the lookup fails.
        """
        try:
            nodes = self._vector_store.get_nodes(filters=self._scope_filters(repo_id, file_path, owner_id))
        except Exception as error:
            logger.exception("Failed to look up chunks for %r in repo %r", file_path, repo_id)
            raise VectorStoreQueryError(f"Failed to look up chunks for {file_path!r}") from error

        return [
            FileChunk(
                file_path=node.metadata["file_path"],
                chunk_name=node.metadata["chunk_name"],
                start_line=node.metadata["start_line"],
                end_line=node.metadata["end_line"],
                text=node.get_content(),
                code=node.metadata.get("code", ""),
            )
            for node in nodes
        ]