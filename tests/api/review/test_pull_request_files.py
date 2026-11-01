"""
    Tests for PullRequestFileFetcher against a fake GitHub client: no network.
"""
import asyncio

import pytest

from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import (
    GitHubFileUnreadableError,
    GitHubPullRequestFetchError,
    GitHubPullRequestNotFoundError,
)
from api.review.pull_request_files import UNREADABLE_FILE_REASON, PullRequestFileFetcher, PullRequestSource
from api.schemas.github import GitHubPullRequestFile

FULL_NAME = "acme/api"
TOKEN = "gho_token"
SOURCE = PullRequestSource(full_name=FULL_NAME, number=7, head_sha="abc123")


class FakeGitHubClient:
    """Stands in for GitHubPullRequestClient: serves canned changed files and file contents, and records the reads."""

    def __init__(
        self,
        changed_files: list[GitHubPullRequestFile],
        contents: dict[str, str] | None = None,
        errors: dict[str, Exception] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._changed_files = changed_files
        self._contents = contents or {}
        self._errors = errors or {}
        self._list_error = list_error
        self.reads: list[tuple[str, str, str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def fetch_changed_files(self, access_token: str, full_name: str, number: int) -> list[GitHubPullRequestFile]:
        if self._list_error:
            raise self._list_error
        return self._changed_files

    async def fetch_file_at_ref(self, access_token: str, full_name: str, path: str, ref: str) -> str:
        self.reads.append((access_token, full_name, path, ref))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        if path in self._errors:
            raise self._errors[path]
        return self._contents.get(path, f"# {path}\n")


def _file(path: str, status: str = "modified") -> GitHubPullRequestFile:
    return GitHubPullRequestFile(path=path, status=status)


def _fetcher(client: FakeGitHubClient, max_concurrent_reads: int = 8) -> PullRequestFileFetcher:
    return PullRequestFileFetcher(client, max_concurrent_reads)


async def _fetch(client: FakeGitHubClient, max_concurrent_reads: int = 8):
    return await _fetcher(client, max_concurrent_reads).fetch(TOKEN, SOURCE)


@pytest.mark.asyncio
async def test_fetch_returns_each_changed_python_file_with_its_content() -> None:
    """Verify the pipeline receives the source of the files the pull request changes."""
    client = FakeGitHubClient([_file("a.py")], contents={"a.py": "x = 1\n"})

    fetched = await _fetch(client)

    assert [(file.file_path, file.content) for file in fetched.files] == [("a.py", "x = 1\n")]


@pytest.mark.asyncio
async def test_fetch_keeps_test_files_so_the_pipeline_can_pair_them() -> None:
    """Verify test files are passed on, since pairing a source file with its tests is the pipeline's job."""
    client = FakeGitHubClient([_file("service.py"), _file("tests/test_service.py")])

    fetched = await _fetch(client)

    assert [file.file_path for file in fetched.files] == ["service.py", "tests/test_service.py"]


@pytest.mark.asyncio
async def test_fetch_leaves_out_files_that_are_not_python() -> None:
    """Verify only Python is read, so a pull request touching docs and configs costs no extra requests."""
    client = FakeGitHubClient([_file("a.py"), _file("README.md"), _file("config.yaml")])

    await _fetch(client)

    assert [read[2] for read in client.reads] == ["a.py"]


@pytest.mark.asyncio
async def test_fetch_leaves_out_removed_files() -> None:
    """Verify a deleted file is not read, since it does not exist at the head commit."""
    client = FakeGitHubClient([_file("a.py"), _file("gone.py", status="removed")])

    await _fetch(client)

    assert [read[2] for read in client.reads] == ["a.py"]


@pytest.mark.asyncio
async def test_fetch_reads_a_renamed_file_at_its_new_path() -> None:
    """Verify a rename is reviewed under the name it has now."""
    client = FakeGitHubClient([_file("new_name.py", status="renamed")])

    fetched = await _fetch(client)

    assert [file.file_path for file in fetched.files] == ["new_name.py"]


@pytest.mark.asyncio
async def test_fetch_reads_every_file_at_the_head_commit_with_the_callers_token() -> None:
    """Verify the review sees the code as the pull request proposes it, read as the user who asked."""
    client = FakeGitHubClient([_file("a.py"), _file("b.py")])

    await _fetch(client)

    assert {(read[0], read[1], read[3]) for read in client.reads} == {(TOKEN, FULL_NAME, "abc123")}


@pytest.mark.asyncio
async def test_fetch_keeps_the_order_of_the_changed_file_list() -> None:
    """Verify concurrent reads do not shuffle the files."""
    paths = [f"f{index}.py" for index in range(12)]
    client = FakeGitHubClient([_file(path) for path in paths])

    fetched = await _fetch(client)

    assert [file.file_path for file in fetched.files] == paths


@pytest.mark.asyncio
async def test_fetch_never_reads_more_files_at_once_than_the_limit() -> None:
    """Verify GitHub is not hit with every request at the same time."""
    client = FakeGitHubClient([_file(f"f{index}.py") for index in range(20)])

    await _fetch(client, max_concurrent_reads=3)

    assert client.max_in_flight <= 3


@pytest.mark.asyncio
async def test_fetch_reports_an_unreadable_file_as_skipped() -> None:
    """Verify one file GitHub cannot return as text is listed with a reason, not dropped silently."""
    client = FakeGitHubClient([_file("big.py")], errors={"big.py": GitHubFileUnreadableError("too large")})

    fetched = await _fetch(client)

    assert [(skipped.file_path, skipped.reason) for skipped in fetched.skipped] == [("big.py", UNREADABLE_FILE_REASON)]


@pytest.mark.asyncio
async def test_fetch_still_returns_the_other_files_when_one_is_unreadable() -> None:
    """Verify an unreadable file does not take the rest of the pull request with it."""
    client = FakeGitHubClient(
        [_file("big.py"), _file("ok.py")], errors={"big.py": GitHubFileUnreadableError("too large")}
    )

    fetched = await _fetch(client)

    assert [file.file_path for file in fetched.files] == ["ok.py"]


@pytest.mark.asyncio
async def test_fetch_with_no_python_files_returns_nothing_to_review() -> None:
    """Verify a pull request with no Python changes is an empty result for the caller to handle, not an error."""
    client = FakeGitHubClient([_file("README.md")])

    fetched = await _fetch(client)

    assert (fetched.files, fetched.skipped) == ([], [])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        GitHubPullRequestFetchError("github is down"),
        GitHubTokenRejectedError("expired"),
    ],
    ids=lambda error: type(error).__name__,
)
async def test_fetch_fails_as_a_whole_when_a_read_fails_for_any_other_reason(error: Exception) -> None:
    """Verify a review never runs on a partial set of files because one read failed."""
    client = FakeGitHubClient([_file("a.py"), _file("b.py")], errors={"b.py": error})

    with pytest.raises(type(error)):
        await _fetch(client)


@pytest.mark.asyncio
async def test_fetch_fails_when_the_changed_file_list_cannot_be_read() -> None:
    """Verify a pull request that disappeared is reported to the caller."""
    client = FakeGitHubClient([], list_error=GitHubPullRequestNotFoundError("gone"))

    with pytest.raises(GitHubPullRequestNotFoundError):
        await _fetch(client)
