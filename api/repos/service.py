import asyncio
import logging
from dataclasses import dataclass

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.indexing.producer import PublishError, RepoIndexProducer
from api.indexing.topics import REPO_FILE_RETRY, REPO_REGISTERED, REPO_STATUS_PROGRESS
from api.integrations.github import (
    PYTHON_PERCENTAGE_THRESHOLD,
    GitHubCommitFetchError,
    GitHubOAuthClient,
    GitHubRepo,
    GitHubRepoFetchError,
)
from api.repos.errors import (
    BranchNotFoundError,
    GitHubVerificationUnavailableError,
    InsufficientPythonError,
    NotRepoOwnerError,
    RepoEventPublishError,
    RepoIdMismatchError,
    RepoPurgeError,
    TooManyIndexJobsError,
)
from api.repos.repository import RegisteredRepoRepository
from api.schemas.indexing import RepoRegisteredMessage
from api.schemas.repos import RegisterRepoRequest, RepoStatusProgressMessage
from api.security.token_cipher import TokenCipher
from code_reviewer.rag.errors import VectorStoreDeletionError
from code_reviewer.rag.indexer import LlamaIndexRagManager

logger = logging.getLogger(__name__)

REGISTRATION_QUEUE_FAILURE = "Could not queue this repo for indexing"
RETRY_QUEUE_FAILURE = "Could not schedule a retry of this repo's failed files"


@dataclass(frozen=True)
class RepoIntegrations:
    """The external systems a registered repo's lifecycle talks to."""

    github_client: GitHubOAuthClient
    token_cipher: TokenCipher
    kafka_producer: RepoIndexProducer
    rag_manager: LlamaIndexRagManager


class RepoLifecycleService:
    """Carries a registered repo through its lifecycle: registration, pause/resume, retry, branch switch, removal."""

    def __init__(
        self, repository: RegisteredRepoRepository, integrations: RepoIntegrations, max_unfinished_indexings: int
    ) -> None:
        self._repository = repository
        self._integrations = integrations
        self._max_unfinished_indexings = max_unfinished_indexings

    async def register(self, request: RegisterRepoRequest, user: User) -> RegisteredRepo:
        if not await self._repository.is_registered(request.repo_id):
            return await self._register_new(request, user)
        existing = await self._repository.find_by_repo_id(request.repo_id)
        return await self._register_existing(existing, request, user)

    async def _register_new(self, request: RegisterRepoRequest, user: User) -> RegisteredRepo:
        await self._require_index_capacity(request.repo_id, user)
        github_repo = await self._verify_registration(request, user)
        registered = RegisteredRepo(
            repo_id=github_repo.repo_id,
            owner_id=github_repo.owner_id,
            full_name=github_repo.full_name,
            default_branch=github_repo.default_branch,
            branch=request.branch or github_repo.default_branch,
            registered_by_user_id=user.id,
            status=RepoIndexStatus.PENDING,
        )
        await self._repository.add(registered)
        await self._publish_registered(registered)
        return registered

    async def _register_existing(
        self, existing: RegisteredRepo, request: RegisterRepoRequest, user: User
    ) -> RegisteredRepo:
        await self._verify_registration(request, user)
        if existing.status == RepoIndexStatus.FAILED and existing.registered_by_user_id == user.id:
            await self._require_index_capacity(existing.repo_id, user)
            existing.branch = request.branch or existing.branch
            await self._restart_indexing(existing)
            return existing
        await self._repository.add_link(user.id, existing.repo_id)
        await self._repository.commit_changes()
        return existing

    async def pause(self, repo: RegisteredRepo, user: User) -> None:
        self._require_owner(repo, user)
        repo.status = RepoIndexStatus.PAUSED
        await self._repository.commit_changes()
        await self._publish_status_progress(repo)

    async def resume(self, repo: RegisteredRepo, user: User) -> None:
        self._require_owner(repo, user)
        await self._require_index_capacity(repo.repo_id, user)
        repo.status = RepoIndexStatus.INDEXING
        await self._repository.commit_changes()
        await self._publish_status_progress(repo)
        await self._publish_registered(repo)

    async def retry_failed_files(self, repo: RegisteredRepo, user: User) -> None:
        self._require_owner(repo, user)
        if not await self._repository.has_failed_files(repo.repo_id):
            return
        await self._require_index_capacity(repo.repo_id, user)
        await self._publish_queued(REPO_FILE_RETRY, self._registration_message(repo), RETRY_QUEUE_FAILURE)
        repo.status = RepoIndexStatus.INDEXING
        await self._repository.commit_changes()
        await self._publish_status_progress(repo)

    async def switch_branch(self, repo: RegisteredRepo, branch: str, user: User) -> None:
        self._require_owner(repo, user)
        await self._require_index_capacity(repo.repo_id, user)
        await self._verify_branch_exists(repo.full_name, branch, user)
        repo.branch = branch
        await self._restart_indexing(repo)

    async def delete(self, repo: RegisteredRepo, user: User) -> None:
        if repo.registered_by_user_id != user.id:
            await self._repository.remove_link(user.id, repo.repo_id)
            await self._repository.commit_changes()
            return
        # Purge the vector store before the registration row: if the purge fails, the repo
        # stays registered (still authorized) rather than leaving unowned content behind.
        await self._purge_indexed_content(repo.repo_id)
        await self._repository.remove(repo)
        await self._repository.commit_changes()

    async def _require_index_capacity(self, repo_id: int, user: User) -> None:
        unfinished = await self._repository.count_active_indexing(user.id, repo_id)
        if unfinished >= self._max_unfinished_indexings:
            raise TooManyIndexJobsError(self._max_unfinished_indexings)

    def _require_owner(self, repo: RegisteredRepo, user: User) -> None:
        if repo.registered_by_user_id != user.id:
            raise NotRepoOwnerError()

    async def _verify_registration(self, request: RegisterRepoRequest, user: User) -> GitHubRepo:
        github_repo = await self._fetch_github_repo(request.full_name, user)
        if github_repo.repo_id != request.repo_id:
            raise RepoIdMismatchError("repo_id does not match full_name")
        if not github_repo.has_enough_python:
            raise InsufficientPythonError(
                f"Repo is only {github_repo.python_percentage}% Python; "
                f"must be at least {PYTHON_PERCENTAGE_THRESHOLD}%"
            )
        return github_repo

    async def _fetch_github_repo(self, full_name: str, user: User) -> GitHubRepo:
        access_token = self._access_token_of(user)
        try:
            return await self._integrations.github_client.fetch_repo(access_token, full_name)
        except GitHubRepoFetchError as error:
            raise GitHubVerificationUnavailableError("Could not verify this repo with GitHub") from error

    async def _verify_branch_exists(self, full_name: str, branch: str, user: User) -> None:
        access_token = self._access_token_of(user)
        try:
            await self._integrations.github_client.fetch_branch_commit_sha(access_token, full_name, branch)
        except GitHubCommitFetchError as error:
            raise BranchNotFoundError(f"Branch '{branch}' was not found") from error

    def _access_token_of(self, user: User) -> str:
        return self._integrations.token_cipher.decrypt(user.encrypted_github_token)

    async def _restart_indexing(self, repo: RegisteredRepo) -> None:
        await self._purge_indexed_content(repo.repo_id)
        repo.status = RepoIndexStatus.PENDING
        repo.status_reason = None
        repo.total_files_expected = None
        repo.commit_sha = None
        await self._repository.commit_changes()
        await self._publish_registered(repo)

    async def _purge_indexed_content(self, repo_id: int) -> None:
        """Removes every indexed trace of a repo — vector store first, then the IndexedFile rows —
        without touching the RegisteredRepo row itself, so a deletion and a branch switch share this."""
        try:
            await asyncio.to_thread(self._integrations.rag_manager.delete_repo, str(repo_id))
        except VectorStoreDeletionError as error:
            raise RepoPurgeError("Could not purge this repo's indexed content; repo was not unregistered") from error
        await self._repository.delete_indexed_files(repo_id)

    async def _publish_registered(self, repo: RegisteredRepo) -> None:
        await self._publish_queued(REPO_REGISTERED, self._registration_message(repo), REGISTRATION_QUEUE_FAILURE)

    async def _publish_queued(self, topic: str, message: RepoRegisteredMessage, failure_message: str) -> None:
        try:
            await self._integrations.kafka_producer.publish(topic, message, str(message.repo_id).encode())
        except PublishError as error:
            raise RepoEventPublishError(failure_message) from error

    async def _publish_status_progress(self, repo: RegisteredRepo) -> None:
        message = RepoStatusProgressMessage.from_registered_repo(repo)
        try:
            await self._integrations.kafka_producer.publish(REPO_STATUS_PROGRESS, message, str(repo.repo_id).encode())
        except Exception:
            # A lost notification, not a lost result — repo.status above is already committed.
            logger.exception("Failed to publish repo.status.progress for repo_id=%s", repo.repo_id)

    def _registration_message(self, repo: RegisteredRepo) -> RepoRegisteredMessage:
        return RepoRegisteredMessage(
            repo_id=repo.repo_id,
            owner_id=repo.owner_id,
            full_name=repo.full_name,
            branch=repo.branch,
            registered_by_user_id=repo.registered_by_user_id,
        )
