"""
    Tests for PullRequestSubmissionLoader against fakes: no DB, no GitHub.
"""
import uuid
from datetime import datetime

import pytest

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.review_job_file import ReviewJobFile
from api.db.models.user import User
from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import GitHubPullRequestFetchError, GitHubPullRequestNotFoundError
from api.review.pull_request_files import FetchedPullRequestFiles, PullRequestSource
from api.review.pull_request_loader import (
    NO_PYTHON_FILES_REASON,
    PULL_REQUEST_GONE_REASON,
    REQUESTER_GONE_REASON,
    TOKEN_REJECTED_REASON,
    PullRequestReviewUnavailableError,
    PullRequestSubmissionLoader,
)
from code_reviewer.schemas.review import SkippedFile
from code_reviewer.schemas.submission import SubmittedFile


class FakeFetcher:
    def __init__(self, fetched: FetchedPullRequestFiles | None = None, error: Exception | None = None) -> None:
        self._fetched = fetched or FetchedPullRequestFiles(files=[SubmittedFile(file_path="a.py", content="x = 1\n")], skipped=[])
        self._error = error
        self.calls: list[tuple[str, PullRequestSource]] = []

    async def fetch(self, access_token: str, source: PullRequestSource) -> FetchedPullRequestFiles:
        self.calls.append((access_token, source))
        if self._error:
            raise self._error
        return self._fetched


class FakeTokenCipher:
    def decrypt(self, value: str) -> str:
        return f"plain-{value}"


class FakeSession:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.executed: list[object] = []
        self.added: list[ReviewJobFile] = []
        self.commit_count = 0

    async def scalar(self, statement) -> User | None:
        return self.user

    async def execute(self, statement) -> None:
        self.executed.append(statement)

    def add(self, row: ReviewJobFile) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1


def _user() -> User:
    return User(id=1, github_id=1, github_username="octocat", encrypted_github_token="secret")


def _repo() -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="acme/api",
        default_branch="main",
        branch="main",
        commit_sha="indexed-sha",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
        created_at=datetime(2026, 1, 1),
    )


def _job(**overrides) -> ReviewJob:
    defaults = {
        "id": 5,
        "review_id": uuid.uuid4(),
        "repo_id": 10,
        "requested_by_user_id": 1,
        "file_paths": [],
        "pr_number": 7,
        "head_sha": "head-sha",
        "status": ReviewJobStatus.RUNNING,
    }
    return ReviewJob(**(defaults | overrides))


def _loader(fetcher: FakeFetcher) -> PullRequestSubmissionLoader:
    return PullRequestSubmissionLoader(fetcher, FakeTokenCipher())


@pytest.mark.asyncio
async def test_load_fetches_with_the_requesting_users_decrypted_token() -> None:
    """Verify the pull request is read as the user who asked, not with a shared credential."""
    fetcher = FakeFetcher()

    await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))

    assert fetcher.calls[0][0] == "plain-secret"


@pytest.mark.asyncio
async def test_load_reads_the_pull_request_at_the_commit_pinned_on_the_job() -> None:
    """Verify the review covers the commit that was current at submit time, even if the branch moved."""
    fetcher = FakeFetcher()

    await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))

    assert fetcher.calls[0][1] == PullRequestSource(full_name="acme/api", number=7, head_sha="head-sha")


@pytest.mark.asyncio
async def test_load_returns_the_files_for_the_pipeline() -> None:
    """Verify the pipeline receives the fetched source."""
    loaded = await _loader(FakeFetcher()).load(_job(), _repo(), FakeSession(_user()))

    assert [(file.file_path, file.content) for file in loaded.files] == [("a.py", "x = 1\n")]


@pytest.mark.asyncio
async def test_load_returns_the_files_it_could_not_read() -> None:
    """Verify unreadable files travel with the result so the report can list them."""
    skipped = [SkippedFile(file_path="big.py", reason="pr_file_unreadable")]
    fetched = FetchedPullRequestFiles(files=[SubmittedFile(file_path="a.py", content="x = 1\n")], skipped=skipped)

    loaded = await _loader(FakeFetcher(fetched)).load(_job(), _repo(), FakeSession(_user()))

    assert loaded.skipped == skipped


@pytest.mark.asyncio
async def test_load_stores_each_file_on_the_job() -> None:
    """Verify the source is kept with the review, so the annotated file view has something to show."""
    session = FakeSession(_user())

    await _loader(FakeFetcher()).load(_job(id=5), _repo(), session)

    assert [(row.review_job_id, row.file_path, row.content) for row in session.added] == [(5, "a.py", "x = 1\n")]


@pytest.mark.asyncio
async def test_load_points_the_jobs_file_list_at_the_files_it_read() -> None:
    """Verify a client polling the review sees the real file count, which is unknown at submit time."""
    job = _job(file_paths=[])

    await _loader(FakeFetcher()).load(job, _repo(), FakeSession(_user()))

    assert job.file_paths == ["a.py"]


@pytest.mark.asyncio
async def test_load_replaces_files_stored_by_an_earlier_attempt() -> None:
    """Verify a review run again after a crash does not collide with the files it stored the first time."""
    session = FakeSession(_user())

    await _loader(FakeFetcher()).load(_job(), _repo(), session)

    assert len(session.executed) == 1


@pytest.mark.asyncio
async def test_load_commits_what_it_stored() -> None:
    """Verify the files and the file list are saved before the pipeline starts."""
    session = FakeSession(_user())

    await _loader(FakeFetcher()).load(_job(), _repo(), session)

    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_load_never_indexes_anything_for_the_vector_store() -> None:
    """Verify the loader's only writes are the job's own file rows, since unmerged code must not reach the index."""
    session = FakeSession(_user())

    await _loader(FakeFetcher()).load(_job(), _repo(), session)

    assert {type(row) for row in session.added} == {ReviewJobFile}


@pytest.mark.asyncio
async def test_load_with_no_python_files_says_so() -> None:
    """Verify a pull request with nothing to review is explained to the user, not treated as a crash."""
    fetcher = FakeFetcher(FetchedPullRequestFiles(files=[], skipped=[]))

    with pytest.raises(PullRequestReviewUnavailableError) as raised:
        await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))

    assert raised.value.reason == NO_PYTHON_FILES_REASON


@pytest.mark.asyncio
async def test_load_with_no_python_files_stores_nothing() -> None:
    """Verify an empty pull request leaves the job's files untouched."""
    session = FakeSession(_user())
    fetcher = FakeFetcher(FetchedPullRequestFiles(files=[], skipped=[]))

    with pytest.raises(PullRequestReviewUnavailableError):
        await _loader(fetcher).load(_job(), _repo(), session)

    assert (session.added, session.commit_count) == ([], 0)


@pytest.mark.asyncio
async def test_load_with_an_expired_github_login_asks_the_user_to_sign_in_again() -> None:
    """Verify an expired token is a user-facing reason, not an unexpected failure."""
    fetcher = FakeFetcher(error=GitHubTokenRejectedError("expired"))

    with pytest.raises(PullRequestReviewUnavailableError) as raised:
        await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))

    assert raised.value.reason == TOKEN_REJECTED_REASON


@pytest.mark.asyncio
async def test_load_with_a_pull_request_that_vanished_says_so() -> None:
    """Verify a pull request deleted or hidden after submit is explained to the user."""
    fetcher = FakeFetcher(error=GitHubPullRequestNotFoundError("gone"))

    with pytest.raises(PullRequestReviewUnavailableError) as raised:
        await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))

    assert raised.value.reason == PULL_REQUEST_GONE_REASON


@pytest.mark.asyncio
async def test_load_lets_a_github_outage_through_as_an_unexpected_failure() -> None:
    """Verify an infrastructure failure is not disguised as something the user can fix."""
    fetcher = FakeFetcher(error=GitHubPullRequestFetchError("github is down"))

    with pytest.raises(GitHubPullRequestFetchError):
        await _loader(fetcher).load(_job(), _repo(), FakeSession(_user()))


@pytest.mark.asyncio
async def test_load_when_the_requesting_user_no_longer_exists_says_so() -> None:
    """Verify a deleted account does not crash the worker."""
    with pytest.raises(PullRequestReviewUnavailableError) as raised:
        await _loader(FakeFetcher()).load(_job(), _repo(), FakeSession(None))

    assert raised.value.reason == REQUESTER_GONE_REASON


@pytest.mark.asyncio
async def test_load_for_a_job_without_a_pull_request_is_an_invariant_error() -> None:
    """Verify a job that should have a pull request number and commit but does not fails loudly."""
    with pytest.raises(ValueError):
        await _loader(FakeFetcher()).load(_job(pr_number=None), _repo(), FakeSession(_user()))
