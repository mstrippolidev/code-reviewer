"""
    Loads a pull request review's files from GitHub into the review job, ready for the pipeline.
    The files are kept only as the job's own rows; nothing is ever written to the vector store.
"""
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.registered_repo import RegisteredRepo
from api.db.models.review_job import ReviewJob
from api.db.models.review_job_file import ReviewJobFile
from api.db.models.user import User
from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import GitHubPullRequestNotFoundError
from api.review.pull_request_files import FetchedPullRequestFiles, PullRequestFileFetcher, PullRequestSource
from api.security.token_cipher import TokenCipher
from code_reviewer.schemas.review import SkippedFile
from code_reviewer.schemas.submission import SubmittedFile

TOKEN_REJECTED_REASON = "Your GitHub authorization has expired. Sign in again and resubmit the pull request"
PULL_REQUEST_GONE_REASON = "The pull request was not found, or you can no longer see it on GitHub"
NO_PYTHON_FILES_REASON = "The pull request changes no Python files that could be read"
REQUESTER_GONE_REASON = "The account that requested this review no longer exists"


class PullRequestReviewUnavailableError(Exception):
    """Raised when a pull request review cannot run for a reason the user can act on, such as an expired GitHub login."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoadedPullRequest:
    """The files to hand to the pipeline, and the changed files that could not be read."""

    files: list[SubmittedFile]
    skipped: list[SkippedFile]


class PullRequestSubmissionLoader:
    """Reads a review job's pull request from GitHub as the user who asked, and stores its files on the job."""

    def __init__(self, fetcher: PullRequestFileFetcher, token_cipher: TokenCipher) -> None:
        self._fetcher = fetcher
        self._token_cipher = token_cipher

    async def load(self, job: ReviewJob, repo: RegisteredRepo, session: AsyncSession) -> LoadedPullRequest:
        """Fetches the pull request's Python files at the commit pinned on the job and saves them on the job.

        The job's `file_paths` are set to the files read, so a client polling the review sees the real count.
        Files stored by an earlier attempt of the same job are replaced.

        Raises:
            PullRequestReviewUnavailableError: If the user's GitHub login expired, the pull request is gone,
                or it has no readable Python file.
            GitHubPullRequestFetchError: If GitHub cannot be reached or answers unexpectedly.
        """
        access_token = await self._requester_token(job, session)
        fetched = await self._fetch(access_token, job, repo)
        if not fetched.files:
            raise PullRequestReviewUnavailableError(NO_PYTHON_FILES_REASON)
        await self._store(job, fetched.files, session)
        return LoadedPullRequest(files=fetched.files, skipped=fetched.skipped)

    async def _requester_token(self, job: ReviewJob, session: AsyncSession) -> str:
        """The GitHub token of the user who asked for the review, decrypted."""
        user = await session.scalar(select(User).where(User.id == job.requested_by_user_id))
        if user is None:
            raise PullRequestReviewUnavailableError(REQUESTER_GONE_REASON)
        return self._token_cipher.decrypt(user.encrypted_github_token)

    async def _fetch(self, access_token: str, job: ReviewJob, repo: RegisteredRepo) -> FetchedPullRequestFiles:
        """Fetches the files, turning an expired login or a vanished pull request into an actionable error."""
        if job.pr_number is None or job.head_sha is None:
            raise ValueError(f"Review {job.review_id} has no pull request number and head commit to read")
        source = PullRequestSource(full_name=repo.full_name, number=job.pr_number, head_sha=job.head_sha)
        try:
            return await self._fetcher.fetch(access_token, source)
        except GitHubTokenRejectedError as error:
            raise PullRequestReviewUnavailableError(TOKEN_REJECTED_REASON) from error
        except GitHubPullRequestNotFoundError as error:
            raise PullRequestReviewUnavailableError(PULL_REQUEST_GONE_REASON) from error

    async def _store(self, job: ReviewJob, files: list[SubmittedFile], session: AsyncSession) -> None:
        """Replaces the job's stored files with these and points the job's file list at them."""
        await session.execute(delete(ReviewJobFile).where(ReviewJobFile.review_job_id == job.id))
        for file in files:
            session.add(ReviewJobFile(review_job_id=job.id, file_path=file.file_path, content=file.content))
        job.file_paths = [file.file_path for file in files]
        await session.commit()
