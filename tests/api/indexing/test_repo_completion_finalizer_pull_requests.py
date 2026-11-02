"""
    What RepoCompletionFinalizer does for the pull request reviews waiting on a repo, against fakes.
"""
import pytest

from api.db.models.indexed_file import IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.indexing.repo_completion_finalizer import RepoCompletionFinalizer
from tests.api.indexing.test_repo_completion_finalizer import (
    FakeAsyncSession,
    FakeRepoProducer,
    _make_registered_repo,
    _zero_counts,
)


class FakeReleaser:
    """Stands in for PendingPullRequestReleaser: records what it was asked to settle, or fails."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.released: list[RegisteredRepo] = []
        self.failed: list[int] = []

    async def release(self, repo: RegisteredRepo, session) -> None:
        if self._error:
            raise self._error
        self.released.append(repo)

    async def fail(self, repo_id: int, session) -> None:
        if self._error:
            raise self._error
        self.failed.append(repo_id)


def _finalizer(releaser: FakeReleaser) -> RepoCompletionFinalizer:
    return RepoCompletionFinalizer(FakeRepoProducer(), releaser)


def _session(repo: RegisteredRepo, **counts: int) -> FakeAsyncSession:
    status_counts = _zero_counts() | {IndexedFileStatus(name): count for name, count in counts.items()}
    return FakeAsyncSession(registered_repo=repo, status_counts=status_counts)


@pytest.mark.asyncio
async def test_a_repo_that_completes_releases_the_pull_request_reviews_waiting_on_it() -> None:
    """Verify the reviews that waited for the index are started the moment it is complete."""
    repo = _make_registered_repo(total_files_expected=3)
    releaser = FakeReleaser()

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, indexed=3))

    assert [released.repo_id for released in releaser.released] == [10]


@pytest.mark.asyncio
async def test_a_repo_that_completes_does_not_fail_any_pull_request_review() -> None:
    """Verify success never fails the reviews that were waiting."""
    repo = _make_registered_repo(total_files_expected=3)
    releaser = FakeReleaser()

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, indexed=3))

    assert releaser.failed == []


@pytest.mark.asyncio
async def test_a_repo_whose_files_all_failed_fails_the_pull_request_reviews_waiting_on_it() -> None:
    """Verify a review is not left waiting for an index that will never be usable."""
    repo = _make_registered_repo(total_files_expected=3)
    releaser = FakeReleaser()

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, failed=3))

    assert releaser.failed == [10]


@pytest.mark.asyncio
async def test_a_repo_still_indexing_settles_no_pull_request_review() -> None:
    """Verify nothing is released or failed before every file has reached a final status."""
    repo = _make_registered_repo(total_files_expected=10)
    releaser = FakeReleaser()

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, indexed=4))

    assert (releaser.released, releaser.failed) == ([], [])


@pytest.mark.asyncio
async def test_a_repo_another_caller_already_finalized_settles_no_pull_request_review_twice() -> None:
    """Verify only the caller that wins the guarded transition settles the reviews."""
    repo = _make_registered_repo(total_files_expected=3, status=RepoIndexStatus.COMPLETED)
    releaser = FakeReleaser()

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, indexed=3))

    assert (releaser.released, releaser.failed) == ([], [])


@pytest.mark.asyncio
async def test_a_problem_settling_reviews_does_not_undo_or_hide_the_repo_completing() -> None:
    """Verify a failure in the review step leaves the repo completed and raises nothing."""
    repo = _make_registered_repo(total_files_expected=3)
    releaser = FakeReleaser(error=RuntimeError("database hiccup"))

    await _finalizer(releaser).finalize_if_complete(10, _session(repo, indexed=3))

    assert repo.status == RepoIndexStatus.COMPLETED


@pytest.mark.asyncio
async def test_fail_pull_request_reviews_fails_the_reviews_waiting_on_the_repo() -> None:
    """Verify the indexer's direct-failure path settles the waiting reviews."""
    releaser = FakeReleaser()

    await _finalizer(releaser).fail_pull_request_reviews(10, _session(_make_registered_repo()))

    assert releaser.failed == [10]


@pytest.mark.asyncio
async def test_fail_pull_request_reviews_never_raises() -> None:
    """Verify the indexer, which is already handling a failure, is not hit by a second one."""
    releaser = FakeReleaser(error=RuntimeError("database hiccup"))

    assert await _finalizer(releaser).fail_pull_request_reviews(10, _session(_make_registered_repo())) is None
