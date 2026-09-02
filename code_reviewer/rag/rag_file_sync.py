"""
    Single entry point for keeping every per-file index in sync with the
    others: the explanation-embedding index, the structural-hash index,
    and the raw-code index (which itself serves both the dense and BM25
    duplicate-recall routes). Takes a list rather than one named parameter
    per index, since every index shares the same three-method lifecycle
    shape — a fourth or fifth recall bucket added later needs no change
    here, only one more entry in the list callers build.
"""
from typing import Protocol

from code_reviewer.rag.repo_data import RepoData


class SyncableIndex(Protocol):
    """Lifecycle shape shared by every index RagFileSync keeps aligned."""

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None: ...

    def delete_file(self, repo_id: str, file_path: str) -> None: ...

    def delete_repo(self, repo_id: str) -> None: ...


class RagFileSync:
    """Keeps every registered index in sync with each other, so callers
    never update one and forget another.
    """

    def __init__(self, indexes: list[SyncableIndex]) -> None:
        self._indexes = indexes

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        for index in self._indexes:
            index.index_file(repo_data, file_path, content)

    def delete_file(self, repo_id: str, file_path: str) -> None:
        for index in self._indexes:
            index.delete_file(repo_id, file_path)

    def delete_repo(self, repo_id: str) -> None:
        for index in self._indexes:
            index.delete_repo(repo_id)
