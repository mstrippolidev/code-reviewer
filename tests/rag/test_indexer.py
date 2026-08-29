"""
    Tests for LlamaIndexRagManager: wiring, ordering, and error handling —
    plus a real end-to-end pass through actual Postgres and Ollama.
"""
from collections.abc import Iterator

from llama_index.core import Document
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.schema import BaseNode, TextNode
from llama_index.core.vector_stores import FilterCondition, MetadataFilter, MetadataFilters
from llama_index.core.vector_stores.types import VectorStoreQuery, VectorStoreQueryResult
from llama_index.vector_stores.postgres import PGVectorStore
import pytest
import sqlalchemy

from code_reviewer.agents.llm.base import LLMInterface
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
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager, RepoData, SimilarChunk
from code_reviewer.rag.vector_store import create_vector_store_instance

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "indexer-integration-test-repo"


class _StubPipeline:
    """Fake split-and-embed pipeline: returns pre-built nodes or raises, and
    records the documents it was called with."""

    def __init__(self, nodes: list[BaseNode] | None = None, error: Exception | None = None) -> None:
        self._nodes = nodes if nodes is not None else []
        self._error = error
        self.received_documents: list[Document] = []

    def run(self, documents: list[Document]) -> list[BaseNode]:
        self.received_documents = documents
        if self._error is not None:
            raise self._error
        return self._nodes


class _RecordingVectorStore:
    """Fake vector store recording delete/add calls in the order they happen."""

    def __init__(self, add_error: Exception | None = None, delete_error: Exception | None = None) -> None:
        self.call_order: list[str] = []
        self.deleted_filters: list[MetadataFilters] = []
        self.added_nodes: list[BaseNode] = []
        self._add_error = add_error
        self._delete_error = delete_error

    def delete_nodes(self, filters: MetadataFilters) -> None:
        self.call_order.append("delete_nodes")
        self.deleted_filters.append(filters)
        if self._delete_error is not None:
            raise self._delete_error

    def add(self, nodes: list[BaseNode]) -> list[str]:
        self.call_order.append("add")
        self.added_nodes = nodes
        if self._add_error is not None:
            raise self._add_error
        return [node.node_id for node in nodes]


class _RecordingPipeline(_StubPipeline):
    """Stub pipeline that also logs into a shared call-order list."""

    def __init__(self, call_order: list[str], nodes: list[BaseNode] | None = None) -> None:
        super().__init__(nodes=nodes)
        self._call_order = call_order

    def run(self, documents: list[Document]) -> list[BaseNode]:
        self._call_order.append("run")
        return super().run(documents)


def _build_manager(pipeline: _StubPipeline, vector_store: _RecordingVectorStore) -> LlamaIndexRagManager:
    return LlamaIndexRagManager(vector_store=vector_store, embedding=None, pipeline=pipeline)


class _FakeEmbeddingModel(BaseEmbedding):
    def _get_query_embedding(self, query: str) -> list[float]:
        return [0.1, 0.2]

    def _get_text_embedding(self, text: str) -> list[float]:
        return [0.1, 0.2]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return [0.1, 0.2]


class _FakeEmbeddingProvider(EmbeddingInterface):
    def create_embedding_model(self) -> BaseEmbedding:
        return _FakeEmbeddingModel()

    @property
    def embed_dim(self) -> int:
        return 2


class _FakeChunkExplainer:
    """Fake in place of ChunkExplainer: returns code unchanged, so
    find_similar's unit tests stay fast and don't reach a real LLM."""

    def explain(self, code: str) -> str:
        return code


class _QueryableVectorStore:
    """Fake vector store satisfying the surface VectorStoreIndex.as_retriever()
    needs, recording the query it received and returning a canned result."""

    stores_text = True
    is_embedding_query = True

    def __init__(self, result: VectorStoreQueryResult | None = None, query_error: Exception | None = None) -> None:
        self._result = result or VectorStoreQueryResult(nodes=[], similarities=[], ids=[])
        self._query_error = query_error
        self.received_query: VectorStoreQuery | None = None

    def query(self, query: VectorStoreQuery, **kwargs: object) -> VectorStoreQueryResult:
        self.received_query = query
        if self._query_error is not None:
            raise self._query_error
        return self._result

    def add(self, nodes: list[BaseNode]) -> list[str]:
        return []

    def delete(self, ref_doc_id: str, **kwargs: object) -> None:
        pass

    @property
    def client(self) -> None:
        return None


def _build_manager_for_find_similar(vector_store: _QueryableVectorStore) -> LlamaIndexRagManager:
    return LlamaIndexRagManager(
        vector_store=vector_store,
        embedding=_FakeEmbeddingProvider(),
        explainer=_FakeChunkExplainer(),
        pipeline=_StubPipeline(),
    )


class _GettableVectorStore:
    """Fake vector store satisfying get_file_chunks' needs: records the
    filters it received and returns a canned list of nodes, with no query
    embedding involved."""

    def __init__(self, nodes: list[BaseNode] | None = None, error: Exception | None = None) -> None:
        self._nodes = nodes if nodes is not None else []
        self._error = error
        self.received_filters: MetadataFilters | None = None

    def get_nodes(self, filters: MetadataFilters) -> list[BaseNode]:
        self.received_filters = filters
        if self._error is not None:
            raise self._error
        return self._nodes


def test_index_file_with_no_owner_id_raises_repo_owner_required_error() -> None:
    """Verify indexing is refused when the repo has no owner_id, since
    private content must never be indexed with no owner attached."""
    manager = _build_manager(_StubPipeline(), _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id=None)

    with pytest.raises(RepoOwnerRequiredError):
        manager.index_file(repo_data, "a.py", "print(1)")


def test_index_file_embeds_before_deleting_existing_chunks() -> None:
    """Verify embedding runs before any deletion, so a failed embed never
    leaves a file with its old chunks deleted and nothing to replace them."""
    call_order: list[str] = []
    pipeline = _RecordingPipeline(call_order, nodes=[TextNode(text="print(1)")])
    vector_store = _RecordingVectorStore()
    vector_store.call_order = call_order
    manager = _build_manager(pipeline, vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    manager.index_file(repo_data, "a.py", "print(1)")

    assert call_order == ["run", "delete_nodes", "add"]


def test_index_file_writes_the_nodes_returned_by_the_pipeline() -> None:
    """Verify the exact nodes the pipeline embeds are what gets stored."""
    expected_nodes = [TextNode(text="print(1)")]
    vector_store = _RecordingVectorStore()
    manager = _build_manager(_StubPipeline(nodes=expected_nodes), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    manager.index_file(repo_data, "a.py", "print(1)")

    assert vector_store.added_nodes == expected_nodes


def test_index_file_builds_document_metadata_with_repo_scoping_fields() -> None:
    """Verify the document handed to the pipeline carries every field a
    stored chunk must be scoped and traced by."""
    pipeline = _StubPipeline()
    manager = _build_manager(pipeline, _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    manager.index_file(repo_data, "a.py", "print(1)")

    metadata = pipeline.received_documents[0].metadata
    assert metadata["repo_id"] == "repo-1"
    assert metadata["owner_id"] == "owner-1"
    assert metadata["file_path"] == "a.py"
    assert metadata["commit_sha"] == "sha-1"


def test_index_file_when_embedding_fails_raises_file_embedding_error() -> None:
    """Verify a pipeline failure surfaces as FileEmbeddingError, not a raw
    library exception, so callers have one stable contract to catch."""
    pipeline = _StubPipeline(error=RuntimeError("ollama unreachable"))
    manager = _build_manager(pipeline, _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(FileEmbeddingError):
        manager.index_file(repo_data, "a.py", "print(1)")


def test_index_file_when_embedding_fails_does_not_delete_existing_chunks() -> None:
    """Verify a failed embed leaves old chunks untouched, since deleting is
    only reached once embedding has already succeeded."""
    pipeline = _StubPipeline(error=RuntimeError("ollama unreachable"))
    vector_store = _RecordingVectorStore()
    manager = _build_manager(pipeline, vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(FileEmbeddingError):
        manager.index_file(repo_data, "a.py", "print(1)")

    assert vector_store.call_order == []


def test_index_file_when_vector_store_add_fails_raises_vector_store_write_error() -> None:
    """Verify a failed write surfaces as VectorStoreWriteError, not a raw
    SQLAlchemy/psycopg exception."""
    pipeline = _StubPipeline(nodes=[TextNode(text="print(1)")])
    vector_store = _RecordingVectorStore(add_error=RuntimeError("connection reset"))
    manager = _build_manager(pipeline, vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(VectorStoreWriteError):
        manager.index_file(repo_data, "a.py", "print(1)")


def test_delete_file_scopes_the_filter_to_repo_id_and_file_path() -> None:
    """Verify delete_file's filter matches only the one file in the one
    repo, never the whole repo's chunks."""
    vector_store = _RecordingVectorStore()
    manager = _build_manager(_StubPipeline(), vector_store)

    manager.delete_file("repo-1", "a.py")

    expected = MetadataFilters(
        filters=[
            MetadataFilter(key="repo_id", value="repo-1"),
            MetadataFilter(key="file_path", value="a.py"),
        ],
        condition=FilterCondition.AND,
    )
    assert vector_store.deleted_filters == [expected]


def test_delete_file_when_vector_store_raises_wraps_in_vector_store_deletion_error() -> None:
    """Verify a failed delete surfaces as VectorStoreDeletionError."""
    vector_store = _RecordingVectorStore(delete_error=RuntimeError("connection reset"))
    manager = _build_manager(_StubPipeline(), vector_store)

    with pytest.raises(VectorStoreDeletionError):
        manager.delete_file("repo-1", "a.py")


def test_delete_repo_scopes_the_filter_to_repo_id_only() -> None:
    """Verify delete_repo's filter matches every file in the repo, with no
    file_path narrowing it down to one."""
    vector_store = _RecordingVectorStore()
    manager = _build_manager(_StubPipeline(), vector_store)

    manager.delete_repo("repo-1")

    expected = MetadataFilters(
        filters=[MetadataFilter(key="repo_id", value="repo-1")],
        condition=FilterCondition.AND,
    )
    assert vector_store.deleted_filters == [expected]


def test_delete_repo_when_vector_store_raises_wraps_in_vector_store_deletion_error() -> None:
    """Verify a failed delete surfaces as VectorStoreDeletionError."""
    vector_store = _RecordingVectorStore(delete_error=RuntimeError("connection reset"))
    manager = _build_manager(_StubPipeline(), vector_store)

    with pytest.raises(VectorStoreDeletionError):
        manager.delete_repo("repo-1")


def test_find_similar_scopes_the_query_to_repo_id_and_owner_id() -> None:
    """Verify the query sent to the vector store filters on repo_id AND
    owner_id, not repo_id alone."""
    vector_store = _QueryableVectorStore()
    manager = _build_manager_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    manager.find_similar(repo_data, "def add(a, b): return a + b")

    expected_filters = MetadataFilters(
        filters=[
            MetadataFilter(key="repo_id", value="repo-1"),
            MetadataFilter(key="owner_id", value="owner-1"),
        ],
        condition=FilterCondition.AND,
    )
    assert vector_store.received_query.filters == expected_filters


def test_find_similar_passes_top_k_as_similarity_top_k() -> None:
    """Verify a custom top_k reaches the vector store as similarity_top_k."""
    vector_store = _QueryableVectorStore()
    manager = _build_manager_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    manager.find_similar(repo_data, "def add(a, b): return a + b", top_k=8)

    assert vector_store.received_query.similarity_top_k == 8


def test_find_similar_maps_query_results_to_similar_chunks() -> None:
    """Verify each returned node becomes a SimilarChunk with its file_path,
    chunk_name, line range, text, score, and code."""
    node = TextNode(
        text="def add(a, b): return a + b",
        metadata={
            "file_path": "math_ops.py",
            "chunk_name": "add",
            "start_line": 1,
            "end_line": 1,
            "code": "def add(a, b):\n    return a + b",
        },
    )
    result = VectorStoreQueryResult(nodes=[node], similarities=[0.87], ids=[node.node_id])
    vector_store = _QueryableVectorStore(result=result)
    manager = _build_manager_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    chunks = manager.find_similar(repo_data, "def add(a, b): return a + b")

    assert chunks == [
        SimilarChunk(
            file_path="math_ops.py",
            chunk_name="add",
            start_line=1,
            end_line=1,
            text="def add(a, b): return a + b",
            score=0.87,
            code="def add(a, b):\n    return a + b",
        )
    ]


def test_find_similar_defaults_code_to_empty_string_when_metadata_has_none() -> None:
    """Verify a chunk indexed before the code metadata field existed still
    maps cleanly, instead of raising a KeyError."""
    node = TextNode(
        text="def add(a, b): return a + b",
        metadata={"file_path": "math_ops.py", "chunk_name": "add", "start_line": 1, "end_line": 1},
    )
    result = VectorStoreQueryResult(nodes=[node], similarities=[0.87], ids=[node.node_id])
    vector_store = _QueryableVectorStore(result=result)
    manager = _build_manager_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    chunks = manager.find_similar(repo_data, "def add(a, b): return a + b")

    assert chunks[0].code == ""


def test_find_similar_when_vector_store_raises_wraps_in_vector_store_query_error() -> None:
    """Verify a failed query surfaces as VectorStoreQueryError."""
    vector_store = _QueryableVectorStore(query_error=RuntimeError("connection reset"))
    manager = _build_manager_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(VectorStoreQueryError):
        manager.find_similar(repo_data, "def add(a, b): return a + b")


def test_get_file_chunks_scopes_the_query_to_repo_id_owner_id_and_file_path() -> None:
    """Verify the filter sent to the vector store narrows to the exact
    (repo_id, owner_id, file_path) triple, not repo_id alone."""
    vector_store = _GettableVectorStore()
    manager = _build_manager(_StubPipeline(), vector_store)

    manager.get_file_chunks("repo-1", "owner-1", "math_ops.py")

    expected_filters = MetadataFilters(
        filters=[
            MetadataFilter(key="repo_id", value="repo-1"),
            MetadataFilter(key="file_path", value="math_ops.py"),
            MetadataFilter(key="owner_id", value="owner-1"),
        ],
        condition=FilterCondition.AND,
    )
    assert vector_store.received_filters == expected_filters


def test_get_file_chunks_maps_nodes_to_file_chunks() -> None:
    """Verify each returned node becomes a FileChunk with its file_path,
    chunk_name, line range, explanation text, and code — no score."""
    node = TextNode(
        text="Adds two numbers and returns the sum.",
        metadata={
            "file_path": "math_ops.py",
            "chunk_name": "add",
            "start_line": 1,
            "end_line": 2,
            "code": "def add(a, b):\n    return a + b",
        },
    )
    vector_store = _GettableVectorStore(nodes=[node])
    manager = _build_manager(_StubPipeline(), vector_store)

    chunks = manager.get_file_chunks("repo-1", "owner-1", "math_ops.py")

    assert chunks == [
        FileChunk(
            file_path="math_ops.py",
            chunk_name="add",
            start_line=1,
            end_line=2,
            text="Adds two numbers and returns the sum.",
            code="def add(a, b):\n    return a + b",
        )
    ]


def test_get_file_chunks_when_vector_store_raises_wraps_in_vector_store_query_error() -> None:
    """Verify a failed lookup surfaces as VectorStoreQueryError, not a raw
    SQLAlchemy/psycopg exception."""
    vector_store = _GettableVectorStore(error=RuntimeError("connection reset"))
    manager = _build_manager(_StubPipeline(), vector_store)

    with pytest.raises(VectorStoreQueryError):
        manager.get_file_chunks("repo-1", "owner-1", "math_ops.py")


@pytest.fixture
def integration_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore pointed at an isolated test schema, never the
    production code_reviewer schema."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA)

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    # Only the sync engine is ever used in these tests, so only it needs
    # disposing — the async engine's dispose() requires greenlet, an
    # unneeded dependency for a connection that was never opened here.
    vector_store.client.dispose()


@pytest.fixture
def integration_manager(integration_vector_store: PGVectorStore, small_llm: LLMInterface) -> LlamaIndexRagManager:
    """Real LlamaIndexRagManager — real ExplainedChunkSplitter and real
    find_similar query explaining (both backed by small_llm, so
    --llm-provider selects their backend), real Ollama code embedding, real
    Postgres — built against the isolated test schema."""
    embedding = OllamaCodeEmbeddingProvider()
    explainer = ChunkExplainer(llm=small_llm)
    pipeline = IngestionPipeline(transformations=[ExplainedChunkSplitter(explainer), embedding.create_embedding_model()])
    return LlamaIndexRagManager(
        vector_store=integration_vector_store, embedding=embedding, explainer=explainer, pipeline=pipeline
    )


@pytest.mark.db
@pytest.mark.llm
def test_index_file_stores_real_embedded_chunks_scoped_to_repo_id(
    integration_manager: LlamaIndexRagManager,
    integration_vector_store: PGVectorStore,
) -> None:
    """Verify index_file's real pipeline actually lands embedded chunks in
    Postgres, scoped to the repo_id and file_path they were indexed under."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")

    integration_manager.index_file(repo_data, "math_ops.py", "def add(a, b):\n    return a + b\n")

    with integration_vector_store.client.connect() as connection:
        stored_row_count = connection.execute(
            sqlalchemy.text(
                f"SELECT count(*) FROM {INTEGRATION_TEST_SCHEMA}.data_code_embeddings "
                "WHERE metadata_->>'repo_id' = :repo_id AND metadata_->>'file_path' = :file_path"
            ),
            {"repo_id": INTEGRATION_TEST_REPO_ID, "file_path": "math_ops.py"},
        ).scalar()

    assert stored_row_count > 0


@pytest.mark.db
@pytest.mark.llm
def test_index_file_replaces_rather_than_duplicates_existing_chunks(
    integration_manager: LlamaIndexRagManager,
    integration_vector_store: PGVectorStore,
) -> None:
    """Verify re-indexing the same file replaces its chunks instead of
    accumulating duplicates alongside the old ones."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_manager.index_file(repo_data, "math_ops.py", "def add(a, b):\n    return a + b\n")

    integration_manager.index_file(repo_data, "math_ops.py", "def add(a, b):\n    return a + b + 1\n")

    with integration_vector_store.client.connect() as connection:
        stored_row_count = connection.execute(
            sqlalchemy.text(
                f"SELECT count(*) FROM {INTEGRATION_TEST_SCHEMA}.data_code_embeddings "
                "WHERE metadata_->>'repo_id' = :repo_id AND metadata_->>'file_path' = :file_path"
            ),
            {"repo_id": INTEGRATION_TEST_REPO_ID, "file_path": "math_ops.py"},
        ).scalar()

    assert stored_row_count == 1


@pytest.mark.db
@pytest.mark.llm
def test_find_similar_returns_the_indexed_chunk_for_matching_repo_and_owner(
    integration_manager: LlamaIndexRagManager,
) -> None:
    """Verify find_similar's real embedding + query path returns a chunk
    indexed under the same repo_id and owner_id."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_manager.index_file(repo_data, "math_ops.py", "def add(a, b):\n    return a + b\n")

    chunks = integration_manager.find_similar(repo_data, "def add(a, b):\n    return a + b\n")

    assert any(chunk.file_path == "math_ops.py" for chunk in chunks)


@pytest.mark.db
@pytest.mark.llm
def test_find_similar_excludes_chunks_indexed_under_a_different_owner_id(
    integration_manager: LlamaIndexRagManager,
) -> None:
    """Verify owner_id is enforced as a query filter, not just repo_id."""
    indexed_repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_manager.index_file(indexed_repo_data, "math_ops.py", "def add(a, b):\n    return a + b\n")
    other_owner_repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-2")

    chunks = integration_manager.find_similar(other_owner_repo_data, "def add(a, b):\n    return a + b\n")

    assert chunks == []


@pytest.mark.db
@pytest.mark.llm
def test_find_similar_returns_the_original_code_alongside_a_real_explanation(
    integration_manager: LlamaIndexRagManager,
) -> None:
    """Verify the real explain-then-embed pipeline round-trips the raw code
    unmodified through metadata, while text stays a genuine LLM explanation
    (not the raw code itself, which would mean the pipeline silently skipped
    explaining and stored the wrong representation)."""
    source = "def add(a, b):\n    return a + b\n"
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_manager.index_file(repo_data, "math_ops.py", source)

    chunks = integration_manager.find_similar(repo_data, source)

    match = next(chunk for chunk in chunks if chunk.file_path == "math_ops.py")
    assert match.code.strip() == source.strip()
    assert len(match.text.strip()) > 0
    assert match.text.strip() != match.code.strip()


@pytest.mark.db
@pytest.mark.llm
def test_get_file_chunks_returns_the_original_code_and_a_real_explanation(
    integration_manager: LlamaIndexRagManager,
) -> None:
    """Verify get_file_chunks' exact lookup surfaces the same real code +
    explanation pair that find_similar sees, via a metadata filter rather
    than a similarity search."""
    source = "def add(a, b):\n    return a + b\n"
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_manager.index_file(repo_data, "math_ops.py", source)

    chunks = integration_manager.get_file_chunks(repo_data.repo_id, repo_data.owner_id, "math_ops.py")

    assert len(chunks) == 1
    assert chunks[0].code.strip() == source.strip()
    assert len(chunks[0].text.strip()) > 0
    assert chunks[0].text.strip() != chunks[0].code.strip()
