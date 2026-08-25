"""
    Tests for RagFileSync: verifies both underlying indexes are called
    together, so callers can never update one and forget the other.
"""
from code_reviewer.rag.rag_file_sync import RagFileSync
from code_reviewer.rag.repo_data import RepoData


class _RecordingIndex:
    """Fake index recording which lifecycle calls it received, in order."""

    def __init__(self, call_order: list[str], label: str) -> None:
        self._call_order = call_order
        self._label = label

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        self._call_order.append(f"{self._label}.index_file")

    def delete_file(self, repo_id: str, file_path: str) -> None:
        self._call_order.append(f"{self._label}.delete_file")

    def delete_repo(self, repo_id: str) -> None:
        self._call_order.append(f"{self._label}.delete_repo")


def _build_sync(call_order: list[str]) -> RagFileSync:
    return RagFileSync(
        embedding_index=_RecordingIndex(call_order, "embedding"),
        structural_index=_RecordingIndex(call_order, "structural"),
    )


def test_index_file_updates_both_the_embedding_and_structural_indexes() -> None:
    """Verify index_file reaches both underlying indexes, not just one."""
    call_order: list[str] = []
    sync = _build_sync(call_order)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    sync.index_file(repo_data, "a.py", "print(1)")

    assert call_order == ["embedding.index_file", "structural.index_file"]


def test_delete_file_updates_both_the_embedding_and_structural_indexes() -> None:
    """Verify delete_file reaches both underlying indexes, not just one."""
    call_order: list[str] = []
    sync = _build_sync(call_order)

    sync.delete_file("repo-1", "a.py")

    assert call_order == ["embedding.delete_file", "structural.delete_file"]


def test_delete_repo_updates_both_the_embedding_and_structural_indexes() -> None:
    """Verify delete_repo reaches both underlying indexes, not just one."""
    call_order: list[str] = []
    sync = _build_sync(call_order)

    sync.delete_repo("repo-1")

    assert call_order == ["embedding.delete_repo", "structural.delete_repo"]
