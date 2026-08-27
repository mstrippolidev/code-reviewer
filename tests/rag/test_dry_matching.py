"""
    Tests for dry_matching: pairwise structural-hash comparison across a
    PR's own files, and cross-history lookup — both structural and
    semantic — against a repo's indexed corpus.
"""
import pytest
from sqlalchemy import Engine, create_engine

from code_reviewer.rag.dry_matching import SEMANTIC_MATCH_TOP_K, CrossHistoryDuplicateFinder, find_intra_pr_duplicates
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"
ADD_FUNCTION_TYPE2_RENAMED = "def sum_values(first_value, second_value):\n    return first_value + second_value\n"
ADD_FUNCTION_THIRD_VARIANT = "def total(p, q):\n    return p + q\n"
SUBTRACT_FUNCTION = "def subtract(a, b):\n    return a - b\n"
LOOP_BASED_SUM = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"
BUILTIN_BASED_SUM = "def total(values):\n    return sum(values)\n"
UNPARSEABLE_CONTENT = "def broken(:\n    pass\n"


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
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_chunk_matching_indexed_history_is_found(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk structurally matching already-indexed history is returned."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), repo_data)

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
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), repo_data)

    history_matches = finder.find("math_ops.py", ADD_FUNCTION)

    assert history_matches == []


def test_match_indexed_under_a_different_repo_id_is_not_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify repo scoping is actually forwarded to the lookup, not silently dropped."""
    structural_hash_store.index_file(RepoData(repo_id="other-repo", commit_sha="sha-1", owner_id="owner-1"), "a.py", ADD_FUNCTION)
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    history_matches = finder.find("b.py", ADD_FUNCTION)

    assert history_matches == []


def test_duplicate_indexed_under_a_nested_subfolder_path_is_found(structural_hash_store: StructuralHashStore) -> None:
    """Verify a history match is found regardless of how deep its indexed path is."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "app/services/nested/deep/utils.py", ADD_FUNCTION)
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), repo_data)

    history_matches = finder.find("utils.py", ADD_FUNCTION_TYPE2_RENAMED)

    assert history_matches[0].structural_matches[0].file_path == "app/services/nested/deep/utils.py"


def test_only_chunks_with_a_history_match_are_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a file with one duplicated and one original chunk reports only the duplicated one."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy.py", ADD_FUNCTION)
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), repo_data)
    content = ADD_FUNCTION_TYPE2_RENAMED + "\n\n" + SUBTRACT_FUNCTION

    history_matches = finder.find("new_file.py", content)

    assert [match.chunk.chunk_name for match in history_matches] == ["sum_values"]


def test_unparseable_content_raises_dry_matching_chunking_error(structural_hash_store: StructuralHashStore) -> None:
    """Verify invalid Python surfaces as DryMatchingChunkingError, not a raw CodeChunkingError."""
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"))

    with pytest.raises(DryMatchingChunkingError):
        finder.find("broken.py", UNPARSEABLE_CONTENT)


def test_chunk_with_only_a_semantic_match_is_returned(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk with no exact structural match but a semantic candidate still surfaces."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, text=LOOP_BASED_SUM, score=0.91
    )
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex([semantic_match]), repo_data)

    history_matches = finder.find("new_file.py", BUILTIN_BASED_SUM)

    assert history_matches[0].structural_matches == []
    assert history_matches[0].semantic_matches == [semantic_match]


def test_chunk_with_no_structural_or_semantic_match_returns_no_results(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a chunk matching neither pass produces no results at all."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex(), repo_data)

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_semantic_self_match_is_excluded(structural_hash_store: StructuralHashStore) -> None:
    """Verify a chunk's own previously-indexed self isn't reported as a semantic duplicate of itself."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    self_match = SimilarChunk(file_path="a.py", chunk_name="add", start_line=1, end_line=2, text=ADD_FUNCTION, score=1.0)
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex([self_match]), repo_data)

    history_matches = finder.find("a.py", ADD_FUNCTION)

    assert history_matches == []


def test_chunk_with_both_structural_and_semantic_matches_returns_both(
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a chunk matched by both passes surfaces both kinds of evidence in one result."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, text=LOOP_BASED_SUM, score=0.9
    )
    finder = CrossHistoryDuplicateFinder(structural_hash_store, _FakeEmbeddingIndex([semantic_match]), repo_data)

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
    finder = CrossHistoryDuplicateFinder(structural_hash_store, embedding_index, repo_data)

    finder.find("a.py", ADD_FUNCTION)

    assert embedding_index.received_code == ADD_FUNCTION.rstrip("\n")
    assert embedding_index.received_top_k == SEMANTIC_MATCH_TOP_K
