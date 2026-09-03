"""
    Tests for dry_matching: pairwise structural-hash comparison across a
    PR's own files, and cross-history lookup — structural, semantic,
    raw-code, and lexical — against a repo's indexed corpus.
"""
from typing import Iterator

import pytest
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import Engine, create_engine

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.chunk_explainer import ChunkExplainer
from code_reviewer.rag.code_similarity_index import CodeMatch, CodeSimilarityIndex, LexicalMatch
from code_reviewer.rag.custom_transformation import ExplainedChunkSplitter
from code_reviewer.rag.dry_matching import (
    CODE_MATCH_TOP_K,
    LEXICAL_MATCH_TOP_K,
    SEMANTIC_MATCH_TOP_K,
    CrossHistoryDuplicateFinder,
    DuplicateEvidenceSources,
    find_intra_pr_duplicates,
)
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.indexer import LlamaIndexRagManager, SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore, StructuralMatch
from code_reviewer.rag.vector_store import create_vector_store_instance
from code_reviewer.schemas.submission import SubmittedFile

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"
ADD_FUNCTION_TYPE2_RENAMED = "def sum_values(first_value, second_value):\n    return first_value + second_value\n"
ADD_FUNCTION_THIRD_VARIANT = "def total(p, q):\n    return p + q\n"
SUBTRACT_FUNCTION = "def subtract(a, b):\n    return a - b\n"
LOOP_BASED_SUM = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"
BUILTIN_BASED_SUM = "def total(values):\n    return sum(values)\n"
UNPARSEABLE_CONTENT = "def broken(:\n    pass\n"

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "dry-matching-integration-test-repo"

GUARD_CLAUSE_SUM = (
    "def total(values):\n"
    "    if not values:\n"
    "        return 0\n"
    "    result = 0\n"
    "    for value in values:\n"
    "        result += value\n"
    "    return result\n"
)
SHOUT_FUNCTION = "def shout(message):\n    return message.upper()\n"


@pytest.fixture
def sqlite_engine() -> Engine:
    """A fresh in-memory SQLite engine, isolated per test."""
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def structural_hash_store(sqlite_engine: Engine) -> StructuralHashStore:
    return StructuralHashStore(engine=sqlite_engine, schema_name=None)


class _FakeEmbeddingIndex:
    """Fake in place of LlamaIndexRagManager: returns a canned list of
    semantic matches and records the code/top_k it received."""

    def __init__(self, matches: list[SimilarChunk] | None = None) -> None:
        self._matches = matches if matches is not None else []
        self.received_code: str | None = None
        self.received_top_k: int | None = None

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        self.received_code = code
        self.received_top_k = top_k
        return self._matches


class _FakeCodeSimilarityIndex:
    """Fake in place of CodeSimilarityIndex: returns canned lists of
    raw-code and lexical matches, and records the code/top_k each route
    received."""

    def __init__(
        self, code_matches: list[CodeMatch] | None = None, lexical_matches: list[LexicalMatch] | None = None
    ) -> None:
        self._code_matches = code_matches if code_matches is not None else []
        self._lexical_matches = lexical_matches if lexical_matches is not None else []
        self.received_code_query: str | None = None
        self.received_code_top_k: int | None = None
        self.received_lexical_query: str | None = None
        self.received_lexical_top_k: int | None = None

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[CodeMatch]:
        self.received_code_query = code
        self.received_code_top_k = top_k
        return self._code_matches

    def find_lexical_matches(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[LexicalMatch]:
        self.received_lexical_query = code
        self.received_lexical_top_k = top_k
        return self._lexical_matches


def _build_finder(
    structural_hash_store: StructuralHashStore,
    repo_data: RepoData,
    embedding_index: _FakeEmbeddingIndex | None = None,
    code_similarity_index: _FakeCodeSimilarityIndex | None = None,
) -> CrossHistoryDuplicateFinder:
    evidence_sources = DuplicateEvidenceSources(
        structural_hash_store=structural_hash_store,
        embedding_index=embedding_index or _FakeEmbeddingIndex(),
        code_similarity_index=code_similarity_index or _FakeCodeSimilarityIndex(),
    )
    return CrossHistoryDuplicateFinder(evidence_sources, repo_data)


def test_files_with_no_shared_structure_produce_no_duplicate_groups() -> None:
    """Verify unrelated files never form a duplicate group."""
    files = [SubmittedFile(file_path="a.py", content=ADD_FUNCTION), SubmittedFile(file_path="b.py", content=SUBTRACT_FUNCTION)]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert duplicate_groups == []


def test_identical_function_copy_pasted_across_two_files_is_grouped() -> None:
    """Verify a Type-1 clone across two files is grouped together."""
    files = [SubmittedFile(file_path="a.py", content=ADD_FUNCTION), SubmittedFile(file_path="b.py", content=ADD_FUNCTION)]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert {match.file_path for match in duplicate_groups[0]} == {"a.py", "b.py"}


def test_function_with_renamed_identifiers_across_files_is_grouped() -> None:
    """Verify a Type-2 clone (renamed function and parameters) is still grouped."""
    files = [
        SubmittedFile(file_path="a.py", content=ADD_FUNCTION),
        SubmittedFile(file_path="b.py", content=ADD_FUNCTION_TYPE2_RENAMED),
    ]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert len(duplicate_groups) == 1


def test_repeated_function_within_the_same_file_is_grouped() -> None:
    """Verify two structurally identical functions in one file are grouped, not just cross-file pairs."""
    content = ADD_FUNCTION + "\n\n" + ADD_FUNCTION_TYPE2_RENAMED
    files = [SubmittedFile(file_path="a.py", content=content)]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert {match.chunk_name for match in duplicate_groups[0]} == {"add", "sum_values"}


def test_three_files_sharing_the_same_structure_form_one_group_of_three() -> None:
    """Verify a duplicate group is not limited to pairs."""
    files = [
        SubmittedFile(file_path="a.py", content=ADD_FUNCTION),
        SubmittedFile(file_path="b.py", content=ADD_FUNCTION_TYPE2_RENAMED),
        SubmittedFile(file_path="c.py", content=ADD_FUNCTION_THIRD_VARIANT),
    ]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert len(duplicate_groups[0]) == 3


def test_duplicate_nested_deep_in_a_subfolder_is_grouped_with_a_root_file() -> None:
    """Verify grouping is based on structure alone, never on file path depth."""
    files = [
        SubmittedFile(file_path="utils.py", content=ADD_FUNCTION),
        SubmittedFile(file_path="app/services/nested/deep/utils.py", content=ADD_FUNCTION),
    ]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert {match.file_path for match in duplicate_groups[0]} == {"utils.py", "app/services/nested/deep/utils.py"}


def test_two_unrelated_duplicate_pairs_produce_two_separate_groups() -> None:
    """Verify unrelated duplicate pairs in the same PR are kept apart, not merged into one group."""
    files = [
        SubmittedFile(file_path="a.py", content=ADD_FUNCTION),
        SubmittedFile(file_path="b.py", content=ADD_FUNCTION),
        SubmittedFile(file_path="c.py", content=SUBTRACT_FUNCTION),
        SubmittedFile(file_path="d.py", content=SUBTRACT_FUNCTION),
    ]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert len(duplicate_groups) == 2


def test_semantically_equivalent_but_structurally_different_code_is_not_grouped() -> None:
    """Verify a Type-4 clone (same behavior, different implementation) is out of
    scope for structural hashing — it needs the semantic pass, not this one."""
    files = [SubmittedFile(file_path="a.py", content=LOOP_BASED_SUM), SubmittedFile(file_path="b.py", content=BUILTIN_BASED_SUM)]

    duplicate_groups = find_intra_pr_duplicates(files)

    assert duplicate_groups == []


def test_unparseable_file_raises_dry_matching_chunking_error() -> None:
    """Verify invalid Python surfaces as DryMatchingChunkingError, not a raw CodeChunkingError."""
    files = [SubmittedFile(file_path="broken.py", content=UNPARSEABLE_CONTENT)]

    with pytest.raises(DryMatchingChunkingError):
        find_intra_pr_duplicates(files)


def test_chunk_with_no_history_match_returns_no_results(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk with nothing matching in history produces no results."""
    finder = _build_finder(structural_hash_store, RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_chunk_matching_indexed_history_is_found(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk structurally matching already-indexed history is returned."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    finder = _build_finder(structural_hash_store, repo_data)

    history_matches = finder.find("new_file.py", ADD_FUNCTION_TYPE2_RENAMED)

    assert history_matches[0].structural_matches == [
        StructuralMatch(file_path="legacy/math_ops.py", chunk_name="add", start_line=1, end_line=2)
    ]


def test_reviewing_the_same_already_indexed_file_excludes_the_self_match(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a chunk already indexed under its own file/name isn't reported as duplicating itself."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "math_ops.py", ADD_FUNCTION)
    finder = _build_finder(structural_hash_store, repo_data)

    history_matches = finder.find("math_ops.py", ADD_FUNCTION)

    assert history_matches == []


def test_match_indexed_under_a_different_repo_id_is_not_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify repo scoping is actually forwarded to the lookup, not silently dropped."""
    structural_hash_store.index_file(RepoData(repo_id="other-repo", commit_sha="sha-1", owner_id="owner-1"), "a.py", ADD_FUNCTION)
    finder = _build_finder(structural_hash_store, RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    history_matches = finder.find("b.py", ADD_FUNCTION)

    assert history_matches == []


def test_duplicate_indexed_under_a_nested_subfolder_path_is_found(structural_hash_store: StructuralHashStore) -> None:
    """Verify a history match is found regardless of how deep its indexed path is."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "app/services/nested/deep/utils.py", ADD_FUNCTION)
    finder = _build_finder(structural_hash_store, repo_data)

    history_matches = finder.find("utils.py", ADD_FUNCTION_TYPE2_RENAMED)

    assert history_matches[0].structural_matches[0].file_path == "app/services/nested/deep/utils.py"


def test_only_chunks_with_a_history_match_are_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a file with one duplicated and one original chunk reports only the duplicated one."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy.py", ADD_FUNCTION)
    finder = _build_finder(structural_hash_store, repo_data)
    content = ADD_FUNCTION_TYPE2_RENAMED + "\n\n" + SUBTRACT_FUNCTION

    history_matches = finder.find("new_file.py", content)

    assert [match.chunk.chunk_name for match in history_matches] == ["sum_values"]


def test_unparseable_content_raises_dry_matching_chunking_error(structural_hash_store: StructuralHashStore) -> None:
    """Verify invalid Python surfaces as DryMatchingChunkingError, not a raw CodeChunkingError."""
    finder = _build_finder(structural_hash_store, RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    with pytest.raises(DryMatchingChunkingError):
        finder.find("broken.py", UNPARSEABLE_CONTENT)


def test_chunk_with_only_a_semantic_match_is_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk with no exact structural match but a semantic candidate still surfaces."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py",
        chunk_name="total",
        start_line=1,
        end_line=3,
        text=LOOP_BASED_SUM,
        score=0.91,
        code=LOOP_BASED_SUM,
    )
    finder = _build_finder(structural_hash_store, repo_data, embedding_index=_FakeEmbeddingIndex([semantic_match]))

    history_matches = finder.find("new_file.py", BUILTIN_BASED_SUM)

    assert history_matches[0].structural_matches == []
    assert history_matches[0].semantic_matches == [semantic_match]


def test_chunk_with_no_matches_from_any_bucket_returns_no_results(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a chunk matching no bucket at all produces no results."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    finder = _build_finder(structural_hash_store, repo_data)

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_semantic_self_match_is_excluded(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk's own previously-indexed self isn't reported as a semantic duplicate of itself."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    self_match = SimilarChunk(
        file_path="a.py", chunk_name="add", start_line=1, end_line=2, text=ADD_FUNCTION, score=1.0, code=ADD_FUNCTION
    )
    finder = _build_finder(structural_hash_store, repo_data, embedding_index=_FakeEmbeddingIndex([self_match]))

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_chunk_with_both_structural_and_semantic_matches_returns_both(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a chunk matched by both passes surfaces both kinds of evidence in one result."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py",
        chunk_name="total",
        start_line=1,
        end_line=3,
        text=LOOP_BASED_SUM,
        score=0.9,
        code=LOOP_BASED_SUM,
    )
    finder = _build_finder(structural_hash_store, repo_data, embedding_index=_FakeEmbeddingIndex([semantic_match]))

    history_matches = finder.find("new_file.py", ADD_FUNCTION_TYPE2_RENAMED)

    assert history_matches[0].structural_matches == [
        StructuralMatch(file_path="legacy/math_ops.py", chunk_name="add", start_line=1, end_line=2)
    ]
    assert history_matches[0].semantic_matches == [semantic_match]


def test_semantic_lookup_queries_with_the_chunk_code_and_the_configured_top_k(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify the semantic pass is called with the chunk's own code (find_similar
    explains it internally) and the module's configured top_k, not some other value."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    embedding_index = _FakeEmbeddingIndex()
    finder = _build_finder(structural_hash_store, repo_data, embedding_index=embedding_index)

    finder.find("a.py", ADD_FUNCTION)

    assert embedding_index.received_code == ADD_FUNCTION.rstrip("\n")
    assert embedding_index.received_top_k == SEMANTIC_MATCH_TOP_K


def test_chunk_with_only_a_code_match_is_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk with only a raw-code similarity candidate still surfaces."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    code_match = CodeMatch(file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, code=LOOP_BASED_SUM, score=0.88)
    finder = _build_finder(structural_hash_store, repo_data, code_similarity_index=_FakeCodeSimilarityIndex(code_matches=[code_match]))

    history_matches = finder.find("new_file.py", BUILTIN_BASED_SUM)

    assert history_matches[0].code_matches == [code_match]
    assert history_matches[0].lexical_matches == []


def test_chunk_with_only_a_lexical_match_is_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk with only a BM25 keyword-overlap candidate still surfaces."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    lexical_match = LexicalMatch(file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, code=LOOP_BASED_SUM, score=4.2)
    finder = _build_finder(
        structural_hash_store, repo_data, code_similarity_index=_FakeCodeSimilarityIndex(lexical_matches=[lexical_match])
    )

    history_matches = finder.find("new_file.py", BUILTIN_BASED_SUM)

    assert history_matches[0].code_matches == []
    assert history_matches[0].lexical_matches == [lexical_match]


def test_code_match_self_is_excluded(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk's own previously-indexed self isn't reported as a raw-code duplicate of itself."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    self_match = CodeMatch(file_path="a.py", chunk_name="add", start_line=1, end_line=2, code=ADD_FUNCTION, score=1.0)
    finder = _build_finder(structural_hash_store, repo_data, code_similarity_index=_FakeCodeSimilarityIndex(code_matches=[self_match]))

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_lexical_match_self_is_excluded(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk's own previously-indexed self isn't reported as a lexical duplicate of itself."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    self_match = LexicalMatch(file_path="a.py", chunk_name="add", start_line=1, end_line=2, code=ADD_FUNCTION, score=5.0)
    finder = _build_finder(
        structural_hash_store, repo_data, code_similarity_index=_FakeCodeSimilarityIndex(lexical_matches=[self_match])
    )

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_all_four_buckets_can_surface_together(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk matched by every bucket surfaces all four kinds of evidence in one result."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, text=LOOP_BASED_SUM, score=0.9, code=LOOP_BASED_SUM
    )
    code_match = CodeMatch(file_path="legacy/other.py", chunk_name="other", start_line=1, end_line=2, code=SUBTRACT_FUNCTION, score=0.7)
    lexical_match = LexicalMatch(file_path="legacy/third.py", chunk_name="third", start_line=1, end_line=2, code=SUBTRACT_FUNCTION, score=3.1)
    finder = _build_finder(
        structural_hash_store,
        repo_data,
        embedding_index=_FakeEmbeddingIndex([semantic_match]),
        code_similarity_index=_FakeCodeSimilarityIndex(code_matches=[code_match], lexical_matches=[lexical_match]),
    )

    history_matches = finder.find("new_file.py", ADD_FUNCTION_TYPE2_RENAMED)

    match = history_matches[0]
    assert match.structural_matches == [StructuralMatch(file_path="legacy/math_ops.py", chunk_name="add", start_line=1, end_line=2)]
    assert match.semantic_matches == [semantic_match]
    assert match.code_matches == [code_match]
    assert match.lexical_matches == [lexical_match]


def test_code_and_lexical_lookups_query_with_the_chunk_code_and_their_own_top_k(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify both new routes are called with the chunk's own code and their
    module-configured top_k values, not the semantic pass's."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    code_similarity_index = _FakeCodeSimilarityIndex()
    finder = _build_finder(structural_hash_store, repo_data, code_similarity_index=code_similarity_index)

    finder.find("a.py", ADD_FUNCTION)

    assert code_similarity_index.received_code_query == ADD_FUNCTION.rstrip("\n")
    assert code_similarity_index.received_code_top_k == CODE_MATCH_TOP_K
    assert code_similarity_index.received_lexical_query == ADD_FUNCTION.rstrip("\n")
    assert code_similarity_index.received_lexical_top_k == LEXICAL_MATCH_TOP_K


# --- Real end-to-end: all four buckets against real Postgres/pgvector,
# real Ollama embeddings, a real explainer LLM, and the real cross-encoder
# re-ranker. Nothing here is mocked or faked — this validates that each
# recall signal genuinely fires on a duplicate and stays quiet on unrelated
# code, and whether DRY_RERANK_SCORE_FLOOR's provisional 0.5 actually keeps
# the true duplicate and drops the false one once real cross-encoder scores
# are in play.


@pytest.fixture(scope="module")
def integration_repo_data() -> RepoData:
    return RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")


@pytest.fixture(scope="module")
def integration_structural_store() -> StructuralHashStore:
    """A real StructuralHashStore, isolated per module run — SQLite
    in-memory is a real SQL engine, not a mock, and structural hashing
    itself involves no external service."""
    engine = create_engine("sqlite:///:memory:")
    return StructuralHashStore(engine=engine, schema_name=None)


@pytest.fixture(scope="module")
def integration_explanation_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore pointed at an isolated test schema, never the
    production code_reviewer schema."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA)

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    vector_store.client.dispose()


@pytest.fixture(scope="module")
def integration_rag_manager(
    integration_explanation_vector_store: PGVectorStore, small_llm: LLMInterface
) -> LlamaIndexRagManager:
    """Real LlamaIndexRagManager: real ExplainedChunkSplitter, real Ollama
    code embedding, real Postgres — backed by small_llm so --llm-provider
    selects its backend."""
    embedding = OllamaCodeEmbeddingProvider()
    explainer = ChunkExplainer(llm=small_llm)
    pipeline = IngestionPipeline(transformations=[ExplainedChunkSplitter(explainer), embedding.create_embedding_model()])
    return LlamaIndexRagManager(
        vector_store=integration_explanation_vector_store, embedding=embedding, explainer=explainer, pipeline=pipeline
    )


@pytest.fixture(scope="module")
def integration_code_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore for the raw-code index, isolated test schema and table."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA, table_name="code_raw_embeddings")

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    vector_store.client.dispose()


@pytest.fixture(scope="module")
def integration_code_similarity_index(integration_code_vector_store: PGVectorStore) -> CodeSimilarityIndex:
    """Real CodeSimilarityIndex: real code embedding, real Postgres, no LLM."""
    return CodeSimilarityIndex(vector_store=integration_code_vector_store, embedding=OllamaCodeEmbeddingProvider())


@pytest.fixture(scope="module")
def integration_reranker() -> HistoryMatchReranker:
    """Real HistoryMatchReranker: the real cross-encoder model, at the same
    provisional floor production is configured with."""
    return HistoryMatchReranker(score_floor=get_settings().dry_rerank_score_floor)


@pytest.fixture(scope="module")
def seeded_history(
    integration_structural_store: StructuralHashStore,
    integration_rag_manager: LlamaIndexRagManager,
    integration_code_similarity_index: CodeSimilarityIndex,
    integration_repo_data: RepoData,
) -> None:
    """Indexes one real chunk per bucket into this repo's history, once for
    the whole module — every test below only queries against it, so the
    explainer LLM is only ever called at index time for this one chunk."""
    integration_structural_store.index_file(integration_repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    integration_rag_manager.index_file(integration_repo_data, "legacy/totals.py", LOOP_BASED_SUM)
    integration_code_similarity_index.index_file(integration_repo_data, "legacy/safe_totals.py", GUARD_CLAUSE_SUM)


@pytest.fixture
def integration_finder(
    integration_structural_store: StructuralHashStore,
    integration_rag_manager: LlamaIndexRagManager,
    integration_code_similarity_index: CodeSimilarityIndex,
    integration_repo_data: RepoData,
    seeded_history: None,
) -> CrossHistoryDuplicateFinder:
    sources = DuplicateEvidenceSources(
        structural_hash_store=integration_structural_store,
        embedding_index=integration_rag_manager,
        code_similarity_index=integration_code_similarity_index,
    )
    return CrossHistoryDuplicateFinder(sources, integration_repo_data)


@pytest.mark.db
@pytest.mark.llm
def test_structural_bucket_finds_a_renamed_duplicate(integration_finder: CrossHistoryDuplicateFinder) -> None:
    """Positive: a Type-2 clone of the indexed ADD_FUNCTION is caught by
    the exact structural-hash bucket."""
    history_matches = integration_finder.find("new_file.py", ADD_FUNCTION_TYPE2_RENAMED)

    match = next(match for match in history_matches if match.chunk.chunk_name == "sum_values")
    assert match.structural_matches != []


@pytest.mark.db
@pytest.mark.llm
def test_structural_bucket_stays_quiet_on_unrelated_code(integration_finder: CrossHistoryDuplicateFinder) -> None:
    """Negative: code with a different AST shape from anything indexed
    produces no structural match."""
    history_matches = integration_finder.find("new_file.py", SHOUT_FUNCTION)

    assert all(match.structural_matches == [] for match in history_matches)


@pytest.mark.db
@pytest.mark.llm
def test_semantic_bucket_finds_a_behaviorally_equivalent_duplicate(
    integration_finder: CrossHistoryDuplicateFinder,
) -> None:
    """Positive: BUILTIN_BASED_SUM behaves like the indexed LOOP_BASED_SUM
    (Type-4 clone) — different structure, same explanation."""
    history_matches = integration_finder.find("new_file.py", BUILTIN_BASED_SUM)

    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert any(candidate.file_path == "legacy/totals.py" for candidate in match.semantic_matches)


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_drops_the_unrelated_semantic_candidate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Negative: with only a handful of chunks indexed, the bi-encoder's
    top_k recall returns its closest available candidate for SHOUT_FUNCTION
    even though nothing behaviorally related is indexed — real evidence for
    why a precision pass exists at all. Verify the real cross-encoder, at
    the configured floor, actually drops it."""
    history_matches = integration_finder.find("new_file.py", SHOUT_FUNCTION)
    match = next(match for match in history_matches if match.chunk.chunk_name == "shout")

    reranked = integration_reranker.rerank(SHOUT_FUNCTION, match)

    assert reranked.semantic_matches == []


@pytest.mark.db
@pytest.mark.llm
def test_code_embedding_bucket_finds_a_near_miss_duplicate(integration_finder: CrossHistoryDuplicateFinder) -> None:
    """Positive: LOOP_BASED_SUM is a near-miss of the indexed
    GUARD_CLAUSE_SUM (an inserted early-return guard) — no LLM involved,
    dense raw-code embedding only."""
    history_matches = integration_finder.find("new_file.py", LOOP_BASED_SUM)

    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert any(candidate.file_path == "legacy/safe_totals.py" for candidate in match.code_matches)


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_drops_the_unrelated_code_embedding_candidate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Negative: same story as the semantic bucket — dense recall over a
    tiny corpus still returns its closest candidate for SHOUT_FUNCTION.
    Verify the real cross-encoder, at the configured floor, drops it."""
    history_matches = integration_finder.find("new_file.py", SHOUT_FUNCTION)
    match = next(match for match in history_matches if match.chunk.chunk_name == "shout")

    reranked = integration_reranker.rerank(SHOUT_FUNCTION, match)

    assert reranked.code_matches == []


@pytest.mark.db
@pytest.mark.llm
def test_lexical_bucket_finds_a_shared_vocabulary_duplicate(integration_finder: CrossHistoryDuplicateFinder) -> None:
    """Positive: LOOP_BASED_SUM shares the indexed GUARD_CLAUSE_SUM's
    distinctive identifiers ("total", "values", "result") — no model
    involved, pure BM25 keyword overlap."""
    history_matches = integration_finder.find("new_file.py", LOOP_BASED_SUM)

    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert any(candidate.file_path == "legacy/safe_totals.py" for candidate in match.lexical_matches)


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_drops_the_unrelated_lexical_candidate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Negative: BM25 over a tiny corpus still ranks *something* as the
    least-bad match for SHOUT_FUNCTION, even sharing no real vocabulary.
    Verify the real cross-encoder, at the configured floor, drops it."""
    history_matches = integration_finder.find("new_file.py", SHOUT_FUNCTION)
    match = next(match for match in history_matches if match.chunk.chunk_name == "shout")

    reranked = integration_reranker.rerank(SHOUT_FUNCTION, match)

    assert reranked.lexical_matches == []


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_keeps_the_real_semantic_duplicate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Verify the real cross-encoder, at the configured floor, does not
    discard a genuine Type-4 duplicate the semantic bucket already found."""
    history_matches = integration_finder.find("new_file.py", BUILTIN_BASED_SUM)
    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert match.semantic_matches != []

    reranked = integration_reranker.rerank(BUILTIN_BASED_SUM, match)

    assert any(candidate.file_path == "legacy/totals.py" for candidate in reranked.semantic_matches)


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_keeps_the_real_code_embedding_duplicate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Verify the real cross-encoder, at the configured floor, does not
    discard the genuine near-miss the code-embedding bucket already found."""
    history_matches = integration_finder.find("new_file.py", LOOP_BASED_SUM)
    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert match.code_matches != []

    reranked = integration_reranker.rerank(LOOP_BASED_SUM, match)

    assert any(candidate.file_path == "legacy/safe_totals.py" for candidate in reranked.code_matches)


@pytest.mark.db
@pytest.mark.llm
def test_rerank_floor_keeps_the_real_lexical_duplicate(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> None:
    """Verify the real cross-encoder, at the configured floor, does not
    discard the genuine keyword-overlap match the lexical bucket already
    found."""
    history_matches = integration_finder.find("new_file.py", LOOP_BASED_SUM)
    match = next(match for match in history_matches if match.chunk.chunk_name == "total")
    assert match.lexical_matches != []

    reranked = integration_reranker.rerank(LOOP_BASED_SUM, match)

    assert any(candidate.file_path == "legacy/safe_totals.py" for candidate in reranked.lexical_matches)
