"""
    FastAPI wiring for the pull request submission service, kept out of api/dependencies.py like the OAuth wiring.
"""
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.dependencies import (
    get_db_session,
    get_kafka_producer,
    get_repo_lifecycle_service,
    get_repo_repository,
    get_token_cipher,
)
from api.indexing.producer import RepoIndexProducer
from api.integrations.github_pull_requests import GitHubPullRequestClient
from api.repos.repository import RegisteredRepoRepository
from api.repos.service import RepoLifecycleService
from api.review.pull_request_submission import PullRequestSubmissionDependencies, PullRequestSubmissionService
from api.review.review_capacity import ReviewSlotKeeper, get_review_slot_keeper
from api.security.token_cipher import TokenCipher


def get_github_pull_request_client(request: Request) -> GitHubPullRequestClient:
    """A pull request reader over the app's shared HTTP client."""
    return GitHubPullRequestClient(request.app.state.http_client)


def get_pull_request_submission_service(
    github_client: GitHubPullRequestClient = Depends(get_github_pull_request_client),
    token_cipher: TokenCipher = Depends(get_token_cipher),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    lifecycle_service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
    producer: RepoIndexProducer = Depends(get_kafka_producer),
    session: AsyncSession = Depends(get_db_session),
    slot_keeper: ReviewSlotKeeper = Depends(get_review_slot_keeper),
) -> PullRequestSubmissionService:
    """The submission service for one request, sharing the request's database session with the repo repository."""
    dependencies = PullRequestSubmissionDependencies(
        github_client=github_client,
        token_cipher=token_cipher,
        repository=repository,
        lifecycle_service=lifecycle_service,
        producer=producer,
        session=session,
        slot_keeper=slot_keeper,
        max_changed_files=get_api_settings().max_pull_request_files,
    )
    return PullRequestSubmissionService(dependencies)
