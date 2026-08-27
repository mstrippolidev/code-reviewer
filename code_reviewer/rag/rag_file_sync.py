"""
    Single entry point for keeping a file's embedding index and structural-
    hash index in sync with each other.
"""
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore


class RagFileSync:
    """Keeps a file's embedding index and structural-hash index in sync
    with each other, so callers never index or delete through one and
    forget the other.
    """

    def __init__(self, embedding_index: LlamaIndexRagManager, structural_index: StructuralHashStore) -> None:
        self._embedding_index = embedding_index
        self._structural_index = structural_index

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        self._embedding_index.index_file(repo_data, file_path, content)
        self._structural_index.index_file(repo_data, file_path, content)

    def delete_file(self, repo_id: str, file_path: str) -> None:
        self._embedding_index.delete_file(repo_id, file_path)
        self._structural_index.delete_file(repo_id, file_path)

    def delete_repo(self, repo_id: str) -> None:
        self._embedding_index.delete_repo(repo_id)
        self._structural_index.delete_repo(repo_id)
