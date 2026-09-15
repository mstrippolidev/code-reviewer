import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.engine import DatabaseEngine
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_database_engine,
    get_db_session,
    get_github_oauth_client,
    get_token_cipher,
)
from api.integrations.github import PYTHON_PERCENTAGE_THRESHOLD, GitHubOAuthClient, GitHubRepo, GitHubRepoFetchError
from api.schemas.repos import RegisterRepoRequest, RegisteredRepoRead
from api.security.token_cipher import TokenCipher

INDEXING_NOT_IMPLEMENTED_REASON = "Repo cloning and file indexing is not implemented yet"
INDEXING_STUB_DELAY_SECONDS = 2

router = APIRouter(prefix="/api/repos", tags=["Repos"])


@router.get("")
async def list_registered_repos(
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[RegisteredRepoRead]:
    result = await session.scalars(select(RegisteredRepo))
    return [RegisteredRepoRead.model_validate(repo) for repo in result.all()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(
    request: RegisterRepoRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    github_oauth_client: GitHubOAuthClient = Depends(get_github_oauth_client),
    token_cipher: TokenCipher = Depends(get_token_cipher),
    session: AsyncSession = Depends(get_db_session),
    database_engine: DatabaseEngine = Depends(get_database_engine),
) -> RegisteredRepoRead:
    await _reject_already_registered(request.repo_id, session)
    access_token = token_cipher.decrypt(current_user.encrypted_github_token)
    repo = await _fetch_and_verify_repo(request, access_token, github_oauth_client)

    registered = RegisteredRepo(
        repo_id=repo.repo_id,
        owner_id=repo.owner_id,
        full_name=repo.full_name,
        default_branch=repo.default_branch,
        registered_by_user_id=current_user.id,
        status=RepoIndexStatus.PENDING,
    )
    session.add(registered)
    try:
        await session.commit()
    except IntegrityError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This repo is already registered") from error
    await session.refresh(registered)
    background_tasks.add_task(_index_registered_repo, registered.id, database_engine)
    return RegisteredRepoRead.model_validate(registered)


async def _index_registered_repo(registered_repo_id: int, database_engine: DatabaseEngine) -> None:
    """Stub for the real clone/walk/index_file pipeline, which isn't built yet."""
    async with database_engine.new_session() as session:
        repo = await session.get(RegisteredRepo, registered_repo_id)
        repo.status = RepoIndexStatus.INDEXING
        await session.commit()

        await asyncio.sleep(INDEXING_STUB_DELAY_SECONDS)

        repo.status = RepoIndexStatus.FAILED
        repo.status_reason = INDEXING_NOT_IMPLEMENTED_REASON
        await session.commit()


async def _reject_already_registered(repo_id: int, session: AsyncSession) -> None:
    existing = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This repo is already registered")


async def _fetch_and_verify_repo(
    request: RegisterRepoRequest,
    access_token: str,
    github_oauth_client: GitHubOAuthClient,
) -> GitHubRepo:
    try:
        repo = await github_oauth_client.fetch_repo(access_token, request.full_name)
    except GitHubRepoFetchError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify this repo with GitHub",
        ) from error
    if repo.repo_id != request.repo_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="repo_id does not match full_name")
    if not repo.has_enough_python:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repo is only {repo.python_percentage}% Python; must be at least {PYTHON_PERCENTAGE_THRESHOLD}%",
        )
    return repo
