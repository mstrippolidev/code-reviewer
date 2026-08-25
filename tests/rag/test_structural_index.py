"""
    Tests for StructuralCloneIndex: wiring and error handling against a
    real SQLite engine, plus a real end-to-end pass through Postgres.
"""
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text

from code_reviewer.rag.errors import RepoOwnerRequiredError, StructuralIndexChunkingError
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_clone import compute_structural_hash
from code_reviewer.rag.structural_index import StructuralCloneIndex, StructuralMatch
from code_reviewer.rag.vector_store import build_connection_url

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "structural-index-integration-test-repo"

ADD_FUNCTION = "def add(a, b):\n    return a + b\n"


@pytest.fixture
def sqlite_engine() -> Engine:
    """A fresh in-memory SQLite engine, isolated per test."""
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def structural_index(sqlite_engine: Engine) -> StructuralCloneIndex:
    return StructuralCloneIndex(engine=sqlite_engine, schema_name=None)


def test_index_file_with_no_owner_id_raises_repo_owner_required_error(
    structural_index: StructuralCloneIndex,
) -> None:
    """Verify indexing is refused when the repo has no owner_id, since
    private content must never be indexed with no owner attached."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id=None)

    with pytest.raises(RepoOwnerRequiredError):
        structural_index.index_file(repo_data, "a.py", ADD_FUNCTION)


def test_index_file_with_unparseable_content_raises_structural_index_chunking_error(
    structural_index: StructuralCloneIndex,
) -> None:
    """Verify invalid Python surfaces as StructuralIndexChunkingError, not a raw CodeChunkingError."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    with pytest.raises(StructuralIndexChunkingError):
        structural_index.index_file(repo_data, "a.py", "def broken(:\n    pass\n")


def test_index_file_stores_one_row_per_top_level_chunk(structural_index: StructuralCloneIndex) -> None:
    """Verify each top-level function becomes its own indexed row, findable by its own hash."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    content = ADD_FUNCTION + "\n\ndef subtract(a, b):\n    return a - b\n"

    structural_index.index_file(repo_data, "math_ops.py", content)

    matches = structural_index.find_by_hash("repo-1", "owner-1", compute_structural_hash(ADD_FUNCTION.strip()))
    assert matches == [StructuralMatch(file_path="math_ops.py", chunk_name="add", start_line=1, end_line=2)]


def test_index_file_replaces_rather_than_duplicates_existing_rows(structural_index: StructuralCloneIndex) -> None:
    """Verify re-indexing the same file replaces its rows instead of accumulating duplicates."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_index.index_file(repo_data, "math_ops.py", ADD_FUNCTION)

    structural_index.index_file(repo_data, "math_ops.py", "def add(a, b):\n    return a + b + 1\n")

    old_hash = compute_structural_hash(ADD_FUNCTION.strip())
    assert structural_index.find_by_hash("repo-1", "owner-1", old_hash) == []


def test_find_by_hash_excludes_a_different_owner_id(structural_index: StructuralCloneIndex) -> None:
    """Verify owner_id is enforced as a query filter, not just repo_id."""
    indexed_repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_index.index_file(indexed_repo_data, "math_ops.py", ADD_FUNCTION)

    matches = structural_index.find_by_hash("repo-1", "owner-2", compute_structural_hash(ADD_FUNCTION.strip()))

    assert matches == []


def test_delete_file_removes_only_that_files_rows(structural_index: StructuralCloneIndex) -> None:
    """Verify delete_file leaves other files in the same repo untouched."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_index.index_file(repo_data, "a.py", ADD_FUNCTION)
    structural_index.index_file(repo_data, "b.py", ADD_FUNCTION)

    structural_index.delete_file("repo-1", "a.py")

    matches = structural_index.find_by_hash("repo-1", "owner-1", compute_structural_hash(ADD_FUNCTION.strip()))
    assert [match.file_path for match in matches] == ["b.py"]


def test_delete_repo_removes_every_file_in_the_repo(structural_index: StructuralCloneIndex) -> None:
    """Verify delete_repo purges every indexed file, not just one."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_index.index_file(repo_data, "a.py", ADD_FUNCTION)
    structural_index.index_file(repo_data, "b.py", ADD_FUNCTION)

    structural_index.delete_repo("repo-1")

    matches = structural_index.find_by_hash("repo-1", "owner-1", compute_structural_hash(ADD_FUNCTION.strip()))
    assert matches == []


@pytest.fixture
def integration_engine() -> Iterator[Engine]:
    """Real Postgres engine pointed at an isolated test schema, never the
    production code_reviewer schema."""
    engine = create_engine(build_connection_url("postgresql+psycopg2"))

    yield engine

    with engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {INTEGRATION_TEST_SCHEMA}.structural_hashes WHERE repo_id = :repo_id"),
            {"repo_id": INTEGRATION_TEST_REPO_ID},
        )
    engine.dispose()


@pytest.mark.db
def test_index_file_stores_real_rows_scoped_to_repo_id(integration_engine: Engine) -> None:
    """Verify index_file actually lands rows in Postgres, scoped to repo_id and file_path."""
    index = StructuralCloneIndex(engine=integration_engine, schema_name=INTEGRATION_TEST_SCHEMA)
    repo_data = RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")

    index.index_file(repo_data, "math_ops.py", ADD_FUNCTION)

    matches = index.find_by_hash(INTEGRATION_TEST_REPO_ID, "owner-1", compute_structural_hash(ADD_FUNCTION.strip()))
    assert matches == [StructuralMatch(file_path="math_ops.py", chunk_name="add", start_line=1, end_line=2)]
