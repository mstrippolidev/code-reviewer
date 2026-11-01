"""
    Reads the Python files a pull request changes, at the pull request's head commit, ready to hand to the review pipeline.
"""
import asyncio
import logging
from dataclasses import dataclass

from api.integrations.github_pull_requests import GitHubFileUnreadableError, GitHubPullRequestClient
from code_reviewer.schemas.review import SkippedFile
from code_reviewer.schemas.submission import SubmittedFile

logger = logging.getLogger(__name__)

REMOVED_FILE_STATUS = "removed"
PYTHON_SUFFIX = ".py"
UNREADABLE_FILE_REASON = "pr_file_unreadable"


@dataclass(frozen=True)
class PullRequestSource:
    """Which pull request to read, and the commit its files are read at."""

    full_name: str
    number: int
    head_sha: str


@dataclass(frozen=True)
class FetchedPullRequestFiles:
    """The Python files read from a pull request, and the changed Python files that could not be read."""

    files: list[SubmittedFile]
    skipped: list[SkippedFile]


@dataclass(frozen=True)
class _ReadContext:
    """What every file read in one fetch shares: whose token and which pull request."""

    access_token: str
    source: PullRequestSource


class PullRequestFileFetcher:
    """Collects a pull request's changed Python files; which of them get reviewed is the pipeline's choice."""

    def __init__(self, github_client: GitHubPullRequestClient, max_concurrent_reads: int) -> None:
        self._github_client = github_client
        self._max_concurrent_reads = max_concurrent_reads

    async def fetch(self, access_token: str, source: PullRequestSource) -> FetchedPullRequestFiles:
        """Reads every changed `.py` file that was not removed, as it is at the pull request's head commit.

        A file GitHub cannot return as text is reported as skipped, not as a failure. Any other failure
        (an expired token, GitHub unreachable, a file missing at the commit) fails the whole fetch, so a
        review never silently runs on a partial set of files.

        Raises:
            GitHubPullRequestNotFoundError: If the pull request disappeared.
            GitHubTokenRejectedError: If GitHub no longer accepts the token.
            GitHubPullRequestFetchError: If GitHub cannot be reached or answers unexpectedly.
        """
        changed_files = await self._github_client.fetch_changed_files(access_token, source.full_name, source.number)
        python_paths = [file.path for file in changed_files if _is_reviewable_python_file(file.path, file.status)]
        context = _ReadContext(access_token=access_token, source=source)
        semaphore = asyncio.Semaphore(self._max_concurrent_reads)
        outcomes = await asyncio.gather(
            *(self._read_one(context, path, semaphore) for path in python_paths), return_exceptions=True
        )
        return _split_outcomes(outcomes)

    async def _read_one(self, context: _ReadContext, path: str, semaphore: asyncio.Semaphore) -> SubmittedFile | SkippedFile:
        """Reads one file, turning an unreadable one into a skipped entry and letting every other failure through."""
        async with semaphore:
            try:
                content = await self._github_client.fetch_file_at_ref(
                    context.access_token, context.source.full_name, path, context.source.head_sha
                )
            except GitHubFileUnreadableError as error:
                logger.warning("pull request file skipped path=%s: %s", path, error)
                return SkippedFile(file_path=path, reason=UNREADABLE_FILE_REASON)
        return SubmittedFile(file_path=path, content=content)


def _is_reviewable_python_file(path: str, status: str) -> bool:
    """Whether a changed file is a Python file that still exists at the head commit."""
    return path.endswith(PYTHON_SUFFIX) and status != REMOVED_FILE_STATUS


def _split_outcomes(outcomes: list[SubmittedFile | SkippedFile | BaseException]) -> FetchedPullRequestFiles:
    """Separates read files from skipped ones, and re-raises the first failure so no partial set is returned."""
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    files = [outcome for outcome in outcomes if isinstance(outcome, SubmittedFile)]
    skipped = [outcome for outcome in outcomes if isinstance(outcome, SkippedFile)]
    return FetchedPullRequestFiles(files=files, skipped=skipped)
