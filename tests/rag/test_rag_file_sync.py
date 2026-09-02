"""
    Tests for RagFileSync: verifies every registered index is called
    together, in order, so callers can never update one and forget another.
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
        indexes=[
            _RecordingIndex(call_order, "embedding"),
            _RecordingIndex(call_order, "structural"),
            _RecordingIndex(call_order, "code_similarity"),
        ]
    )


def test_index_file_updates_every_registered_index_in_order() -> None:
    """Verify index_file reaches every registered index, in the order given."""
    call_order: list[str] = []
    sync = _build_sync(call_order)
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")

    sync.index_file(repo_data, "a.py", "print(1)")

    assert call_order == ["embedding.index_file", "structural.index_file", "code_similarity.index_file"]


def test_delete_file_updates_every_registered_index_in_order() -> None:
    """Verify delete_file reaches every registered index, in the order given."""
    call_order: list[str] = []
    sync = _build_sync(call_order)

    sync.delete_file("repo-1", "a.py")

    assert call_order == ["embedding.delete_file", "structural.delete_file", "code_similarity.delete_file"]


def test_delete_repo_updates_every_registered_index_in_order() -> None:
    """Verify delete_repo reaches every registered index, in the order given."""
    call_order: list[str] = []
    sync = _build_sync(call_order)

    sync.delete_repo("repo-1")

    assert call_order == ["embedding.delete_repo", "structural.delete_repo", "code_similarity.delete_repo"]


def test_a_single_registered_index_still_receives_every_call() -> None:
    """Verify the list-based design works with just one index too, not only three."""
    call_order: list[str] = []
    sync = RagFileSync(indexes=[_RecordingIndex(call_order, "only")])

    sync.index_file(RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1"), "a.py", "print(1)")

    assert call_order == ["only.index_file"]
