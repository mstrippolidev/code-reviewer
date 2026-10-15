"""
    Tests for RepoContentPurger against fakes: no real vector store, no real DB.
"""
import pytest

from api.repos.content_purger import RepoContentPurger
from api.repos.errors import RepoPurgeError
from code_reviewer.rag.errors import VectorStoreDeletionError


class FakeVectorStore:
    def __init__(self, calls: list[tuple[str, object]], delete_error: Exception | None = None) -> None:
        self._calls = calls
        self._delete_error = delete_error

    def delete_repo(self, repo_id: str) -> None:
        if self._delete_error:
            raise self._delete_error
        self._calls.append(("vector_store", repo_id))


class FakeIndexedFiles:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self._calls = calls

    async def delete_indexed_files(self, repo_id: int) -> None:
        self._calls.append(("indexed_files", repo_id))


@pytest.mark.asyncio
async def test_purge_removes_the_vector_store_content_before_the_database_rows() -> None:
    """Verify the order, and that the vector store is addressed by string id and the rows by int id.

    Rows go last so a failed purge never leaves embeddings behind with no row pointing at them.
    """
    calls: list[tuple[str, object]] = []
    purger = RepoContentPurger(FakeVectorStore(calls), FakeIndexedFiles(calls))

    await purger.purge(10)

    assert calls == [("vector_store", "10"), ("indexed_files", 10)]


@pytest.mark.asyncio
async def test_purge_reports_a_vector_store_failure_with_a_client_safe_message() -> None:
    """Verify that a failed embeddings delete is raised as a purge error."""
    calls: list[tuple[str, object]] = []
    store = FakeVectorStore(calls, delete_error=VectorStoreDeletionError("pgvector timeout"))
    purger = RepoContentPurger(store, FakeIndexedFiles(calls))

    with pytest.raises(RepoPurgeError, match="Could not purge this repo's indexed content"):
        await purger.purge(10)


@pytest.mark.asyncio
async def test_purge_keeps_the_database_rows_when_the_vector_store_delete_fails() -> None:
    """Verify that nothing else is deleted after the vector store fails.

    The repo must stay fully registered so the purge can be retried.
    """
    calls: list[tuple[str, object]] = []
    store = FakeVectorStore(calls, delete_error=VectorStoreDeletionError("pgvector timeout"))
    purger = RepoContentPurger(store, FakeIndexedFiles(calls))

    with pytest.raises(RepoPurgeError):
        await purger.purge(10)

    assert calls == []
