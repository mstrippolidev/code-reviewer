import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_github_oauth_client,
    get_kafka_producer,
    get_rag_manager,
    get_token_cipher,
)
from api.indexing.producer import PublishError, RepoIndexProducer
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.indexing.topics import REPO_FILE_RETRY, REPO_REGISTERED, REPO_STATUS_PROGRESS
from api.integrations.github import PYTHON_PERCENTAGE_THRESHOLD, GitHubOAuthClient, GitHubRepo, GitHubRepoFetchError
from api.schemas.indexing import RepoRegisteredMessage
from api.schemas.repos import (
    IndexedFileRead,
    RegisterRepoRequest,
    RegisteredRepoRead,
    RepoFileProgressMessage,
    RepoStatusProgressMessage,
)
from api.security.token_cipher import TokenCipher
from code_reviewer.rag.errors import VectorStoreDeletionError
from code_reviewer.rag.indexer import LlamaIndexRagManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repos", tags=["Repos"])

_TERMINAL_REPO_STATUSES = frozenset({RepoIndexStatus.COMPLETED, RepoIndexStatus.FAILED})
_STREAM_CLOSING_STATUSES = _TERMINAL_REPO_STATUSES | {RepoIndexStatus.PAUSED}


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
    current_user: User = Depends(get_current_user),
    github_oauth_client: GitHubOAuthClient = Depends(get_github_oauth_client),
    token_cipher: TokenCipher = Depends(get_token_cipher),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
    session: AsyncSession = Depends(get_db_session),
) -> RegisteredRepoRead:
    await _reject_active_registration(request.repo_id, session)
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
    await _publish_repo_registered(registered, kafka_producer)
    return RegisteredRepoRead.model_validate(registered)


async def _publish_repo_registered(registered: RegisteredRepo, kafka_producer: RepoIndexProducer) -> None:
    message = RepoRegisteredMessage(
        repo_id=registered.repo_id,
        owner_id=registered.owner_id,
        full_name=registered.full_name,
        default_branch=registered.default_branch,
        registered_by_user_id=registered.registered_by_user_id,
    )
    try:
        await kafka_producer.publish(REPO_REGISTERED, message, str(message.repo_id).encode())
    except PublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not queue this repo for indexing",
        ) from error


async def _reject_active_registration(repo_id: int, session: AsyncSession) -> None:
    existing = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
    if existing is None:
        return
    if existing.status != RepoIndexStatus.FAILED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This repo is already registered")
    await session.delete(existing)
    await session.flush()


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


@router.get("/{repo_id}/files")
async def list_indexed_files(
    repo_id: int,
    _current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[IndexedFileRead]:
    await _get_registered_repo_or_404(repo_id, session)
    files = await _get_indexed_files(repo_id, session)
    return [IndexedFileRead.model_validate(file) for file in files]


async def _get_registered_repo_or_404(repo_id: int, session: AsyncSession) -> RegisteredRepo:
    repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Repo {repo_id} is not registered")
    return repo


async def _get_indexed_files(repo_id: int, session: AsyncSession) -> list[IndexedFile]:
    result = await session.scalars(select(IndexedFile).where(IndexedFile.repo_id == repo_id))
    return list(result.all())


async def _require_registered_repo(
    repo_id: int, session: AsyncSession = Depends(get_db_session)
) -> RegisteredRepo:
    return await _get_registered_repo_or_404(repo_id, session)


@router.get("/{repo_id}/files/stream", response_class=EventSourceResponse)
async def stream_indexed_files(
    request: Request,
    repo: RegisteredRepo = Depends(_require_registered_repo),
    session: AsyncSession = Depends(get_db_session),
    _current_user: User = Depends(get_current_user),
) -> AsyncIterator[ServerSentEvent]:
    broadcaster: RepoProgressBroadcaster = request.app.state.repo_progress_broadcaster
    queue = broadcaster.subscribe(repo.repo_id)
    try:
        yield ServerSentEvent(event="status", data=_current_repo_status(repo))
        files = await _get_indexed_files(repo.repo_id, session)
        for file in files:
            yield ServerSentEvent(event="file", data=IndexedFileRead.model_validate(file))
        if repo.status in _STREAM_CLOSING_STATUSES:
            return
        while True:
            event = await queue.get()
            if isinstance(event, RepoStatusProgressMessage):
                yield ServerSentEvent(event="status", data=event)
                if event.status in _STREAM_CLOSING_STATUSES:
                    return
            elif isinstance(event, RepoFileProgressMessage):
                yield ServerSentEvent(event="file", data=event)
    finally:
        broadcaster.unsubscribe(repo.repo_id, queue)


def _current_repo_status(repo: RegisteredRepo) -> RepoStatusProgressMessage:
    return RepoStatusProgressMessage(
        repo_id=repo.repo_id,
        status=repo.status,
        status_reason=repo.status_reason,
        total_files_expected=repo.total_files_expected,
    )


@router.post("/{repo_id}/pause")
async def pause_repo_indexing(
    repo: RegisteredRepo = Depends(_require_registered_repo),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.INDEXING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not currently indexing")
    repo.status = RepoIndexStatus.PAUSED
    await session.commit()
    await _publish_status_progress(kafka_producer, repo)
    return RegisteredRepoRead.model_validate(repo)


@router.post("/{repo_id}/resume")
async def resume_repo_indexing(
    repo: RegisteredRepo = Depends(_require_registered_repo),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not paused")
    repo.status = RepoIndexStatus.INDEXING
    await session.commit()
    await _publish_status_progress(kafka_producer, repo)
    await _publish_repo_registered(repo, kafka_producer)
    return RegisteredRepoRead.model_validate(repo)


async def _publish_status_progress(kafka_producer: RepoIndexProducer, repo: RegisteredRepo) -> None:
    try:
        await kafka_producer.publish(REPO_STATUS_PROGRESS, _current_repo_status(repo), str(repo.repo_id).encode())
    except Exception:
        # A lost notification, not a lost result — repo.status above is already committed.
        logger.exception("Failed to publish repo.status.progress for repo_id=%s", repo.repo_id)


@router.post("/{repo_id}/files/retry")
async def retry_failed_files(
    repo: RegisteredRepo = Depends(_require_registered_repo),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status not in _TERMINAL_REPO_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo indexing has not finished yet")
    has_failed_files = await session.scalar(
        select(IndexedFile.id)
        .where(IndexedFile.repo_id == repo.repo_id, IndexedFile.status == IndexedFileStatus.FAILED)
        .limit(1)
    )
    if has_failed_files is None:
        return RegisteredRepoRead.model_validate(repo)
    await _publish_retry(repo, kafka_producer)
    repo.status = RepoIndexStatus.INDEXING
    await session.commit()
    await _publish_status_progress(kafka_producer, repo)
    return RegisteredRepoRead.model_validate(repo)


async def _publish_retry(repo: RegisteredRepo, kafka_producer: RepoIndexProducer) -> None:
    message = RepoRegisteredMessage(
        repo_id=repo.repo_id,
        owner_id=repo.owner_id,
        full_name=repo.full_name,
        default_branch=repo.default_branch,
        registered_by_user_id=repo.registered_by_user_id,
    )
    try:
        await kafka_producer.publish(REPO_FILE_RETRY, message, str(repo.repo_id).encode())
    except PublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not schedule a retry of this repo's failed files",
        ) from error


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registered_repo(
    repo: RegisteredRepo = Depends(_require_registered_repo),
    session: AsyncSession = Depends(get_db_session),
    rag_manager: LlamaIndexRagManager = Depends(get_rag_manager),
    _current_user: User = Depends(get_current_user),
) -> None:
    # Purge the vector store before the registration row: if the purge fails, the repo
    # stays registered (still authorized) rather than leaving unowned content behind.
    await _purge_vector_store_content(repo.repo_id, rag_manager)
    await session.execute(delete(IndexedFile).where(IndexedFile.repo_id == repo.repo_id))
    await session.delete(repo)
    await session.commit()


async def _purge_vector_store_content(repo_id: int, rag_manager: LlamaIndexRagManager) -> None:
    try:
        await asyncio.to_thread(rag_manager.delete_repo, str(repo_id))
    except VectorStoreDeletionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not purge this repo's indexed content; repo was not unregistered",
        ) from error