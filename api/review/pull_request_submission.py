"""
    Accepts a pull request for review: checks it against GitHub, finds or registers its repo, and queues the job
    now, or leaves it waiting until the repo has finished indexing.
"""
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.indexing.producer import PublishError, RepoIndexProducer
from api.integrations.github import GitHubTokenRejectedError
from api.integrations.github_pull_requests import (
    GitHubPullRequestClient,
    GitHubPullRequestFetchError,
    GitHubPullRequestNotFoundError,
)
from api.repos.errors import GitHubAuthorizationExpiredError
from api.repos.repository import RegisteredRepoRepository
from api.repos.service import RepoLifecycleService
from api.review.pull_request_errors import (
    PullRequestBaseBranchError,
    PullRequestNotFoundError,
    PullRequestNotOpenError,
    PullRequestQueueError,
    PullRequestRepoNotReadyError,
    PullRequestTooLargeError,
    PullRequestUnavailableError,
)
from api.review.pull_request_queue import NOT_QUEUED_REASON, publish_pull_request_review
from api.review.review_capacity import ReviewSlotKeeper
from api.schemas.github import GitHubPullRequest
from api.schemas.pull_requests import PullRequestReviewRequest
from api.schemas.repos import RegisterRepoRequest
from api.security.token_cipher import TokenCipher

logger = logging.getLogger(__name__)

OPEN_PULL_REQUEST_STATE = "open"
WAITING_FOR_INDEX_REASON = "Waiting for the repo to finish indexing"
NOT_QUEUEABLE_STATUSES = frozenset({RepoIndexStatus.FAILED, RepoIndexStatus.PAUSED})


@dataclass(frozen=True)
class PullRequestSubmissionDependencies:
    """Everything the submission service talks to, so the service itself stays about the order of the steps."""

    github_client: GitHubPullRequestClient
    token_cipher: TokenCipher
    repository: RegisteredRepoRepository
    lifecycle_service: RepoLifecycleService
    producer: RepoIndexProducer
    session: AsyncSession
    slot_keeper: ReviewSlotKeeper
    max_changed_files: int


class PullRequestSubmissionService:
    """Turns a pull request URL into a review job that is queued now or waits for its repo's index."""

    def __init__(self, dependencies: PullRequestSubmissionDependencies) -> None:
        self._dependencies = dependencies

    async def submit(self, request: PullRequestReviewRequest, user: User) -> ReviewJob:
        """Checks the pull request, finds or registers its repo, and creates the review job.

        The job is published at once when the repo is fully indexed. When the repo is still pending or
        indexing, the job is only stored as `pending` with a reason, and published later by the release step.

        Raises:
            PullRequestNotFoundError: If GitHub has no such pull request or the user cannot see it.
            GitHubAuthorizationExpiredError: If GitHub no longer accepts the user's token.
            PullRequestUnavailableError: If GitHub cannot be reached or answers unexpectedly.
            PullRequestNotOpenError: If the pull request is closed or merged.
            PullRequestTooLargeError: If it changes more files than a review accepts.
            PullRequestBaseBranchError: If it targets a branch other than the one the repo's index follows.
            PullRequestRepoNotReadyError: If the repo's indexing failed or is paused.
            PullRequestQueueError: If the review cannot be queued.
        """
        pull_request = await self._read_reviewable_pull_request(request, user)
        repo = await self._resolve_repo(pull_request, user)
        _require_queueable(pull_request, repo)
        job = await self._create_job(request, pull_request, repo, user)
        if repo.status == RepoIndexStatus.COMPLETED:
            await self._publish(job, repo)
        return job

    async def _read_reviewable_pull_request(self, request: PullRequestReviewRequest, user: User) -> GitHubPullRequest:
        """Reads the pull request as the user and refuses one that is closed or too large to review."""
        reference = request.pull_request
        access_token = self._dependencies.token_cipher.decrypt(user.encrypted_github_token)
        try:
            pull_request = await self._dependencies.github_client.fetch_pull_request(
                access_token, reference.full_name, reference.number
            )
        except GitHubPullRequestNotFoundError as error:
            raise PullRequestNotFoundError(
                f"Pull request {reference.number} was not found in {reference.full_name}, or you cannot see it"
            ) from error
        except GitHubTokenRejectedError as error:
            raise GitHubAuthorizationExpiredError("GitHub authorization expired, please log in again") from error
        except GitHubPullRequestFetchError as error:
            logger.error("Could not read pull request %s#%s", reference.full_name, reference.number, exc_info=True)
            raise PullRequestUnavailableError("Could not read the pull request from GitHub. Try again shortly") from error
        self._require_open_and_small(pull_request)
        return pull_request

    def _require_open_and_small(self, pull_request: GitHubPullRequest) -> None:
        """Refuses a closed or merged pull request, and one that changes more files than the review limit."""
        if pull_request.state != OPEN_PULL_REQUEST_STATE or pull_request.merged:
            raise PullRequestNotOpenError(pull_request.number)
        limit = self._dependencies.max_changed_files
        if pull_request.changed_files > limit:
            raise PullRequestTooLargeError(pull_request.changed_files, limit)

    async def _resolve_repo(self, pull_request: GitHubPullRequest, user: User) -> RegisteredRepo:
        """The registered repo the pull request targets; an unregistered one is registered, following the base branch."""
        repository = self._dependencies.repository
        if await repository.is_registered(pull_request.base_repo_id):
            return await repository.find_by_repo_id(pull_request.base_repo_id)
        registration = RegisterRepoRequest(
            repo_id=pull_request.base_repo_id,
            full_name=pull_request.base_repo_full_name,
            branch=pull_request.base_ref,
        )
        return await self._dependencies.lifecycle_service.register(registration, user)

    async def _create_job(
        self, request: PullRequestReviewRequest, pull_request: GitHubPullRequest, repo: RegisteredRepo, user: User
    ) -> ReviewJob:
        """Stores the review job pinned to the pull request's head commit, with a reason if it has to wait.

        Takes the user's review slot first. Everything slow (GitHub, registration) is already done, so the slot
        lock is held only for the insert and commit below.
        """
        await self._dependencies.slot_keeper.reserve(user.id)
        is_waiting = repo.status != RepoIndexStatus.COMPLETED
        job = ReviewJob(
            review_id=uuid.uuid4(),
            repo_id=repo.repo_id,
            requested_by_user_id=user.id,
            file_paths=[],
            pr_number=pull_request.number,
            head_sha=pull_request.head_sha,
            agents=[agent.value for agent in request.agents] if request.agents else None,
            status=ReviewJobStatus.PENDING,
            status_reason=WAITING_FOR_INDEX_REASON if is_waiting else None,
        )
        session = self._dependencies.session
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    async def _publish(self, job: ReviewJob, repo: RegisteredRepo) -> None:
        """Queues the job; if Kafka refuses it, fails the job so it is not left pending for a worker that will never see it."""
        try:
            await publish_pull_request_review(self._dependencies.producer, job, repo)
        except PublishError as error:
            job.status = ReviewJobStatus.FAILED
            job.status_reason = NOT_QUEUED_REASON
            await self._dependencies.session.commit()
            raise PullRequestQueueError(NOT_QUEUED_REASON) from error


def _require_queueable(pull_request: GitHubPullRequest, repo: RegisteredRepo) -> None:
    """Refuses a pull request aimed at a branch the index does not follow, or a repo whose indexing cannot proceed."""
    if pull_request.base_ref != repo.branch:
        raise PullRequestBaseBranchError(pull_request.base_ref, repo.branch)
    if repo.status in NOT_QUEUEABLE_STATUSES:
        raise PullRequestRepoNotReadyError(repo.status.value)
