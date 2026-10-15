import asyncio
from typing import Protocol

from api.repos.errors import RepoPurgeError
from code_reviewer.rag.errors import VectorStoreDeletionError


class VectorStoreCleaner(Protocol):
    """Contract for anything that can delete a repo's embeddings."""

    def delete_repo(self, repo_id: str) -> None: ...


class IndexedFileStore(Protocol):
    """Contract for anything that can delete a repo's indexed-file rows."""

    async def delete_indexed_files(self, repo_id: int) -> None: ...


class RepoContentPurger:
    """Removes every indexed trace of a repo — vector store first, then the IndexedFile rows —
    without touching the RegisteredRepo row itself, so a deletion and a branch switch share this."""

    def __init__(self, vector_store: VectorStoreCleaner, indexed_files: IndexedFileStore) -> None:
        self._vector_store = vector_store
        self._indexed_files = indexed_files

    async def purge(self, repo_id: int) -> None:
        await self._purge_vector_store(repo_id)
        await self._indexed_files.delete_indexed_files(repo_id)

    async def _purge_vector_store(self, repo_id: int) -> None:
        try:
            await asyncio.to_thread(self._vector_store.delete_repo, str(repo_id))
        except VectorStoreDeletionError as error:
            raise RepoPurgeError(
                "Could not purge this repo's indexed content; repo was not unregistered"
            ) from error
