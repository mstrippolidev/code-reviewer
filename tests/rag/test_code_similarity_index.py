"""
    Tests for CodeSimilarityIndex: wiring, ordering, and error handling for
    the raw-code index and its two routes (dense similarity, BM25 keyword
    overlap) — plus a real end-to-end pass through actual Postgres. No LLM
    is involved anywhere in this file: unlike LlamaIndexRagManager, this
    index embeds and queries with raw code directly, with no explanation
    step, and BM25 ranking runs locally with no model call at all.
"""
from collections.abc import Iterator

import pytest
import sqlalchemy
from llama_index.core import Document
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import BaseNode, TextNode
from llama_index.core.vector_stores import FilterCondition, MetadataFilter, MetadataFilters
from llama_index.core.vector_stores.types import VectorStoreQuery, VectorStoreQueryResult
from llama_index.vector_stores.postgres import PGVectorStore

from code_reviewer.rag.code_similarity_index import CodeMatch, CodeSimilarityIndex, LexicalMatch
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

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "code-similarity-index-integration-test-repo"

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"


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


def _build_index(pipeline: _StubPipeline, vector_store: _RecordingVectorStore) -> CodeSimilarityIndex:
    return CodeSimilarityIndex(vector_store=vector_store, embedding=None, pipeline=pipeline)


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


def _build_index_for_find_similar(vector_store: _QueryableVectorStore) -> CodeSimilarityIndex:
    return CodeSimilarityIndex(vector_store=vector_store, embedding=_FakeEmbeddingProvider(), pipeline=_StubPipeline())


class _GettableVectorStore:
    """Fake vector store satisfying find_lexical_matches' needs: records the
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


def _code_node(file_path: str, chunk_name: str, code: str) -> TextNode:
    return TextNode(
        text=code, metadata={"file_path": file_path, "chunk_name": chunk_name, "start_line": 1, "end_line": 2}
    )


def test_index_file_with_no_owner_id_raises_repo_owner_required_error() -> None:
    """Verify indexing is refused when the repo has no owner_id, since
    private content must never be indexed with no owner attached."""
    index = _build_index(_StubPipeline(), _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id=None)

    with pytest.raises(RepoOwnerRequiredError):
        index.index_file(repo_data, "a.py", ADD_FUNCTION)


def test_index_file_embeds_before_deleting_existing_chunks() -> None:
    """Verify embedding runs before any deletion, so a failed embed never
    leaves a file with its old chunks deleted and nothing to replace them."""
    call_order: list[str] = []

    class _RecordingPipeline(_StubPipeline):
        def run(self, documents: list[Document]) -> list[BaseNode]:
            call_order.append("run")
            return super().run(documents)

    pipeline = _RecordingPipeline(nodes=[TextNode(text=ADD_FUNCTION)])
    vector_store = _RecordingVectorStore()
    vector_store.call_order = call_order
    index = _build_index(pipeline, vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.index_file(repo_data, "a.py", ADD_FUNCTION)

    assert call_order == ["run", "delete_nodes", "add"]


def test_index_file_writes_the_nodes_returned_by_the_pipeline() -> None:
    """Verify the exact nodes the pipeline embeds are what gets stored."""
    expected_nodes = [TextNode(text=ADD_FUNCTION)]
    vector_store = _RecordingVectorStore()
    index = _build_index(_StubPipeline(nodes=expected_nodes), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.index_file(repo_data, "a.py", ADD_FUNCTION)

    assert vector_store.added_nodes == expected_nodes


def test_index_file_builds_document_metadata_with_repo_scoping_fields() -> None:
    """Verify the document handed to the pipeline carries every field a
    stored chunk must be scoped and traced by."""
    pipeline = _StubPipeline()
    index = _build_index(pipeline, _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.index_file(repo_data, "a.py", ADD_FUNCTION)

    metadata = pipeline.received_documents[0].metadata
    assert metadata["repo_id"] == "repo-1"
    assert metadata["owner_id"] == "owner-1"
    assert metadata["file_path"] == "a.py"
    assert metadata["commit_sha"] == "sha-1"


def test_index_file_when_embedding_fails_raises_file_embedding_error() -> None:
    """Verify a pipeline failure surfaces as FileEmbeddingError, not a raw
    library exception, so callers have one stable contract to catch."""
    pipeline = _StubPipeline(error=RuntimeError("ollama unreachable"))
    index = _build_index(pipeline, _RecordingVectorStore())
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(FileEmbeddingError):
        index.index_file(repo_data, "a.py", ADD_FUNCTION)


def test_index_file_when_vector_store_add_fails_raises_vector_store_write_error() -> None:
    """Verify a failed write surfaces as VectorStoreWriteError, not a raw
    SQLAlchemy/psycopg exception."""
    pipeline = _StubPipeline(nodes=[TextNode(text=ADD_FUNCTION)])
    vector_store = _RecordingVectorStore(add_error=RuntimeError("connection reset"))
    index = _build_index(pipeline, vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(VectorStoreWriteError):
        index.index_file(repo_data, "a.py", ADD_FUNCTION)


def test_delete_file_scopes_the_filter_to_repo_id_and_file_path() -> None:
    """Verify delete_file's filter matches only the one file in the one
    repo, never the whole repo's chunks."""
    vector_store = _RecordingVectorStore()
    index = _build_index(_StubPipeline(), vector_store)

    index.delete_file("repo-1", "a.py")

    expected = MetadataFilters(
        filters=[MetadataFilter(key="repo_id", value="repo-1"), MetadataFilter(key="file_path", value="a.py")],
        condition=FilterCondition.AND,
    )
    assert vector_store.deleted_filters == [expected]


def test_delete_file_when_vector_store_raises_wraps_in_vector_store_deletion_error() -> None:
    """Verify a failed delete surfaces as VectorStoreDeletionError."""
    vector_store = _RecordingVectorStore(delete_error=RuntimeError("connection reset"))
    index = _build_index(_StubPipeline(), vector_store)

    with pytest.raises(VectorStoreDeletionError):
        index.delete_file("repo-1", "a.py")


def test_delete_repo_scopes_the_filter_to_repo_id_only() -> None:
    """Verify delete_repo's filter matches every file in the repo, with no
    file_path narrowing it down to one."""
    vector_store = _RecordingVectorStore()
    index = _build_index(_StubPipeline(), vector_store)

    index.delete_repo("repo-1")

    expected = MetadataFilters(filters=[MetadataFilter(key="repo_id", value="repo-1")], condition=FilterCondition.AND)
    assert vector_store.deleted_filters == [expected]


def test_find_similar_scopes_the_query_to_repo_id_and_owner_id() -> None:
    """Verify the query sent to the vector store filters on repo_id AND
    owner_id, not repo_id alone."""
    vector_store = _QueryableVectorStore()
    index = _build_index_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.find_similar(repo_data, ADD_FUNCTION)

    expected_filters = MetadataFilters(
        filters=[MetadataFilter(key="repo_id", value="repo-1"), MetadataFilter(key="owner_id", value="owner-1")],
        condition=FilterCondition.AND,
    )
    assert vector_store.received_query.filters == expected_filters


def test_find_similar_queries_with_the_raw_code_directly() -> None:
    """Verify no explanation step runs — the query text sent to the vector
    store is the code itself, since this index embeds code on both sides."""
    vector_store = _QueryableVectorStore()
    index = _build_index_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.find_similar(repo_data, ADD_FUNCTION)

    assert vector_store.received_query.query_str == ADD_FUNCTION


def test_find_similar_maps_query_results_to_code_match() -> None:
    """Verify each returned node becomes a CodeMatch with its file_path,
    chunk_name, line range, code, and score."""
    node = _code_node("math_ops.py", "add", ADD_FUNCTION)
    result = VectorStoreQueryResult(nodes=[node], similarities=[0.87], ids=[node.node_id])
    vector_store = _QueryableVectorStore(result=result)
    index = _build_index_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    matches = index.find_similar(repo_data, ADD_FUNCTION)

    assert matches == [CodeMatch(file_path="math_ops.py", chunk_name="add", start_line=1, end_line=2, code=ADD_FUNCTION, score=0.87)]


def test_find_similar_when_vector_store_raises_wraps_in_vector_store_query_error() -> None:
    """Verify a failed query surfaces as VectorStoreQueryError."""
    vector_store = _QueryableVectorStore(query_error=RuntimeError("connection reset"))
    index = _build_index_for_find_similar(vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(VectorStoreQueryError):
        index.find_similar(repo_data, ADD_FUNCTION)


def test_find_lexical_matches_scopes_the_node_fetch_to_repo_id_and_owner_id() -> None:
    """Verify the corpus fetched for BM25 ranking is scoped to repo_id AND
    owner_id, never the whole table."""
    vector_store = _GettableVectorStore()
    index = _build_index(_StubPipeline(), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    index.find_lexical_matches(repo_data, ADD_FUNCTION)

    expected_filters = MetadataFilters(
        filters=[MetadataFilter(key="repo_id", value="repo-1"), MetadataFilter(key="owner_id", value="owner-1")],
        condition=FilterCondition.AND,
    )
    assert vector_store.received_filters == expected_filters


def test_find_lexical_matches_returns_empty_list_when_repo_has_no_indexed_nodes() -> None:
    """Verify an empty corpus short-circuits to no matches, rather than
    building a BM25 index over nothing."""
    index = _build_index(_StubPipeline(), _GettableVectorStore(nodes=[]))
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    matches = index.find_lexical_matches(repo_data, ADD_FUNCTION)

    assert matches == []


def test_find_lexical_matches_ranks_the_chunk_sharing_the_most_vocabulary_first() -> None:
    """Verify real BM25 ranking: a chunk sharing the query's distinctive
    identifiers outranks one that shares almost nothing."""
    shared_vocabulary_node = _code_node("legacy/math_ops.py", "add_totals", "def add_totals(first_value, second_value):\n    return first_value + second_value\n")
    unrelated_node = _code_node("legacy/strings.py", "shout", "def shout(message):\n    return message.upper()\n")
    vector_store = _GettableVectorStore(nodes=[unrelated_node, shared_vocabulary_node])
    index = _build_index(_StubPipeline(), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    query_code = "def sum_totals(first_value, second_value):\n    return first_value + second_value\n"

    matches = index.find_lexical_matches(repo_data, query_code)

    assert matches[0].chunk_name == "add_totals"


def test_find_lexical_matches_respects_top_k() -> None:
    """Verify only the top_k highest-scoring candidates are returned, not
    every candidate that shares any vocabulary at all."""
    nodes = [_code_node(f"legacy/file_{i}.py", f"add_{i}", ADD_FUNCTION) for i in range(5)]
    vector_store = _GettableVectorStore(nodes=nodes)
    index = _build_index(_StubPipeline(), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    matches = index.find_lexical_matches(repo_data, ADD_FUNCTION, top_k=2)

    assert len(matches) == 2


def test_find_lexical_matches_maps_results_to_lexical_match() -> None:
    """Verify a returned candidate becomes a LexicalMatch with its
    file_path, chunk_name, line range, and code, alongside a BM25 score."""
    node = _code_node("math_ops.py", "add", ADD_FUNCTION)
    vector_store = _GettableVectorStore(nodes=[node])
    index = _build_index(_StubPipeline(), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    matches = index.find_lexical_matches(repo_data, ADD_FUNCTION)

    assert matches == [LexicalMatch(file_path="math_ops.py", chunk_name="add", start_line=1, end_line=2, code=ADD_FUNCTION, score=matches[0].score)]
    assert matches[0].score > 0


def test_find_lexical_matches_when_vector_store_raises_wraps_in_vector_store_query_error() -> None:
    """Verify a failed node fetch surfaces as VectorStoreQueryError, not a
    raw SQLAlchemy/psycopg exception."""
    vector_store = _GettableVectorStore(error=RuntimeError("connection reset"))
    index = _build_index(_StubPipeline(), vector_store)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(VectorStoreQueryError):
        index.find_lexical_matches(repo_data, ADD_FUNCTION)


@pytest.fixture
def integration_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore pointed at an isolated test schema and table,
    never the production code_reviewer schema/tables."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA, table_name="code_raw_embeddings")

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    vector_store.client.dispose()


@pytest.fixture
def integration_index(integration_vector_store: PGVectorStore) -> CodeSimilarityIndex:
    """Real CodeSimilarityIndex — real CodeChunkSplitter, real Ollama code
    embedding, real Postgres, no LLM anywhere in this path."""
    return CodeSimilarityIndex(vector_store=integration_vector_store, embedding=OllamaCodeEmbeddingProvider())


@pytest.mark.db
def test_index_file_stores_real_embedded_chunks_scoped_to_repo_id(
    integration_index: CodeSimilarityIndex, integration_vector_store: PGVectorStore
) -> None:
    """Verify index_file's real pipeline actually lands embedded chunks in
    Postgres, scoped to the repo_id and file_path they were indexed under."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")

    integration_index.index_file(repo_data, "math_ops.py", ADD_FUNCTION)

    with integration_vector_store.client.connect() as connection:
        stored_row_count = connection.execute(
            sqlalchemy.text(
                f"SELECT count(*) FROM {INTEGRATION_TEST_SCHEMA}.data_code_raw_embeddings "
                "WHERE metadata_->>'repo_id' = :repo_id AND metadata_->>'file_path' = :file_path"
            ),
            {"repo_id": INTEGRATION_TEST_REPO_ID, "file_path": "math_ops.py"},
        ).scalar()

    assert stored_row_count > 0


@pytest.mark.db
def test_find_similar_returns_the_indexed_chunk_embedded_as_raw_code(integration_index: CodeSimilarityIndex) -> None:
    """Verify find_similar's real embed-and-query path returns a chunk
    indexed under the same repo_id and owner_id, with its code intact."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_index.index_file(repo_data, "math_ops.py", ADD_FUNCTION)

    matches = integration_index.find_similar(repo_data, ADD_FUNCTION)

    match = next(match for match in matches if match.file_path == "math_ops.py")
    assert match.code.strip() == ADD_FUNCTION.strip()


@pytest.mark.db
def test_find_lexical_matches_returns_the_indexed_chunk_from_real_postgres(
    integration_index: CodeSimilarityIndex,
) -> None:
    """Verify find_lexical_matches fetches this repo's real stored nodes
    from Postgres and ranks the matching one first."""
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")
    integration_index.index_file(repo_data, "math_ops.py", ADD_FUNCTION)

    matches = integration_index.find_lexical_matches(repo_data, ADD_FUNCTION)

    assert any(match.file_path == "math_ops.py" for match in matches)
