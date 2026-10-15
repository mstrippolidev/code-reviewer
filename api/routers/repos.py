from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_repo_content_purger,
    get_repo_event_publisher,
    get_repo_github_verifier,
    get_repo_repository,
    require_registered_repo,
)
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.repos.content_purger import RepoContentPurger
from api.repos.event_publisher import RepoEventPublisher
from api.repos.github_verifier import RepoGitHubVerifier
from api.repos.repository import RegisteredRepoRepository
from api.schemas.repos import (
    IndexedFileContentRead,
    IndexedFileRead,
    RegisteredRepoRead,
    RegisteredRepoWithFilesRead,
    RegisterRepoRequest,
    RepoFileProgressMessage,
    RepoStatusProgressMessage,
    SwitchBranchRequest,
)

router = APIRouter(prefix="/api/repos", tags=["Repos"])

_TERMINAL_REPO_STATUSES = frozenset({RepoIndexStatus.COMPLETED, RepoIndexStatus.FAILED})
_STREAM_CLOSING_STATUSES = _TERMINAL_REPO_STATUSES | {RepoIndexStatus.PAUSED}


@router.get("")
async def list_registered_repos(
    _current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> list[RegisteredRepoRead]:
    repos = await repository.list_all()
    return [RegisteredRepoRead.model_validate(repo) for repo in repos]


@router.get("/name")
async def get_repo_by_name(
    full_name: str = Query(min_length=1),
    with_files: bool = False,
    _current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> RegisteredRepoWithFilesRead:
    repo = await repository.find_by_full_name(full_name)
    files = await repository.list_indexed_files(repo.repo_id) if with_files else []
    return RegisteredRepoWithFilesRead(
        repo=RegisteredRepoRead.model_validate(repo),
        files=[IndexedFileRead.model_validate(file) for file in files],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(
    request: RegisterRepoRequest,
    current_user: User = Depends(get_current_user),
    verifier: RepoGitHubVerifier = Depends(get_repo_github_verifier),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    publisher: RepoEventPublisher = Depends(get_repo_event_publisher),
) -> RegisteredRepoRead:
    await repository.reject_active_registration(request.repo_id)
    github_repo = await verifier.verify_registration(request, current_user)

    registered = RegisteredRepo(
        repo_id=github_repo.repo_id,
        owner_id=github_repo.owner_id,
        full_name=github_repo.full_name,
        default_branch=github_repo.default_branch,
        branch=request.branch or github_repo.default_branch,
        registered_by_user_id=current_user.id,
        status=RepoIndexStatus.PENDING,
    )
    await repository.add(registered)
    await publisher.publish_registered(registered)
    return RegisteredRepoRead.model_validate(registered)


@router.get("/{repo_id}/files")
async def list_indexed_files(
    _current_user: User = Depends(get_current_user),
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> list[IndexedFileRead]:
    files = await repository.list_indexed_files(repo.repo_id)
    return [IndexedFileRead.model_validate(file) for file in files]


@router.get("/{repo_id}/files/content")
async def get_indexed_file_content(
    file_path: str,
    repo: RegisteredRepo = Depends(require_registered_repo),
    _current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> IndexedFileContentRead:
    file = await repository.find_indexed_content(repo.repo_id, file_path)
    return IndexedFileContentRead.model_validate(file)


@router.get("/{repo_id}/files/stream", response_class=EventSourceResponse)
async def stream_indexed_files(
    request: Request,
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    _current_user: User = Depends(get_current_user),
) -> AsyncIterator[ServerSentEvent]:
    broadcaster: RepoProgressBroadcaster = request.app.state.repo_progress_broadcaster
    queue = broadcaster.subscribe(repo.repo_id)
    try:
        yield ServerSentEvent(event="status", data=RepoStatusProgressMessage.from_registered_repo(repo))
        files = await repository.list_indexed_files(repo.repo_id)
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


@router.post("/{repo_id}/pause")
async def pause_repo_indexing(
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    publisher: RepoEventPublisher = Depends(get_repo_event_publisher),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.INDEXING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not currently indexing")
    repo.status = RepoIndexStatus.PAUSED
    await repository.commit_changes()
    await publisher.publish_status_progress(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.post("/{repo_id}/resume")
async def resume_repo_indexing(
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    publisher: RepoEventPublisher = Depends(get_repo_event_publisher),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not paused")
    repo.status = RepoIndexStatus.INDEXING
    await repository.commit_changes()
    await publisher.publish_status_progress(repo)
    await publisher.publish_registered(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.post("/{repo_id}/files/retry")
async def retry_failed_files(
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    publisher: RepoEventPublisher = Depends(get_repo_event_publisher),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status not in _TERMINAL_REPO_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo indexing has not finished yet")
    if not await repository.has_failed_files(repo.repo_id):
        return RegisteredRepoRead.model_validate(repo)
    await publisher.publish_file_retry(repo)
    repo.status = RepoIndexStatus.INDEXING
    await repository.commit_changes()
    await publisher.publish_status_progress(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registered_repo(
    repo: RegisteredRepo = Depends(require_registered_repo),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    purger: RepoContentPurger = Depends(get_repo_content_purger),
    _current_user: User = Depends(get_current_user),
) -> None:
    # Purge the vector store before the registration row: if the purge fails, the repo
    # stays registered (still authorized) rather than leaving unowned content behind.
    await purger.purge(repo.repo_id)
    await repository.remove(repo)
    await repository.commit_changes()


@router.post("/{repo_id}/branch")
async def switch_repo_branch(
    request: SwitchBranchRequest,
    repo: RegisteredRepo = Depends(require_registered_repo),
    current_user: User = Depends(get_current_user),
    verifier: RepoGitHubVerifier = Depends(get_repo_github_verifier),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    purger: RepoContentPurger = Depends(get_repo_content_purger),
    publisher: RepoEventPublisher = Depends(get_repo_event_publisher),
) -> RegisteredRepoRead:
    await verifier.verify_branch_exists(repo.full_name, request.branch, current_user)
    await purger.purge(repo.repo_id)
    repo.branch = request.branch
    repo.status = RepoIndexStatus.PENDING
    repo.status_reason = None
    repo.total_files_expected = None
    repo.commit_sha = None
    await repository.commit_changes()
    await publisher.publish_registered(repo)
    return RegisteredRepoRead.model_validate(repo)
