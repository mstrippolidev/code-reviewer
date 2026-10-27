from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_repo_access_checker,
    get_repo_lifecycle_service,
    get_repo_repository,
    require_github_repo_access,
)
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.repos.access import RepoAccessChecker
from api.repos.repository import RegisteredRepoRepository
from api.repos.service import RepoLifecycleService
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
    current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> list[RegisteredRepoRead]:
    repos = await repository.list_registered_by(current_user.id)
    return [RegisteredRepoRead.model_validate(repo) for repo in repos]


@router.get("/name")
async def get_repo_by_name(
    full_name: str = Query(min_length=1),
    with_files: bool = False,
    current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
    access_checker: RepoAccessChecker = Depends(get_repo_access_checker),
) -> RegisteredRepoWithFilesRead:
    repo = await repository.find_by_full_name(full_name)
    await access_checker.require_access(current_user, repo)
    files = await repository.list_indexed_files(repo.repo_id) if with_files else []
    return RegisteredRepoWithFilesRead(
        repo=RegisteredRepoRead.model_validate(repo),
        files=[IndexedFileRead.model_validate(file) for file in files],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(
    request: RegisterRepoRequest,
    current_user: User = Depends(get_current_user),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
) -> RegisteredRepoRead:
    registered = await service.register(request, current_user)
    return RegisteredRepoRead.model_validate(registered)


@router.get("/{repo_id}/files")
async def list_indexed_files(
    _current_user: User = Depends(get_current_user),
    repo: RegisteredRepo = Depends(require_github_repo_access),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> list[IndexedFileRead]:
    files = await repository.list_indexed_files(repo.repo_id)
    return [IndexedFileRead.model_validate(file) for file in files]


@router.get("/{repo_id}/files/content")
async def get_indexed_file_content(
    file_path: str,
    repo: RegisteredRepo = Depends(require_github_repo_access),
    _current_user: User = Depends(get_current_user),
    repository: RegisteredRepoRepository = Depends(get_repo_repository),
) -> IndexedFileContentRead:
    file = await repository.find_indexed_content(repo.repo_id, file_path)
    return IndexedFileContentRead.model_validate(file)


@router.get("/{repo_id}/files/stream", response_class=EventSourceResponse)
async def stream_indexed_files(
    request: Request,
    repo: RegisteredRepo = Depends(require_github_repo_access),
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
    repo: RegisteredRepo = Depends(require_github_repo_access),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.INDEXING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not currently indexing")
    await service.pause(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.post("/{repo_id}/resume")
async def resume_repo_indexing(
    repo: RegisteredRepo = Depends(require_github_repo_access),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status != RepoIndexStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not paused")
    await service.resume(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.post("/{repo_id}/files/retry")
async def retry_failed_files(
    repo: RegisteredRepo = Depends(require_github_repo_access),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
    _current_user: User = Depends(get_current_user),
) -> RegisteredRepoRead:
    if repo.status not in _TERMINAL_REPO_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo indexing has not finished yet")
    await service.retry_failed_files(repo)
    return RegisteredRepoRead.model_validate(repo)


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registered_repo(
    repo: RegisteredRepo = Depends(require_github_repo_access),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
    _current_user: User = Depends(get_current_user),
) -> None:
    await service.delete(repo)


@router.post("/{repo_id}/branch")
async def switch_repo_branch(
    request: SwitchBranchRequest,
    repo: RegisteredRepo = Depends(require_github_repo_access),
    current_user: User = Depends(get_current_user),
    service: RepoLifecycleService = Depends(get_repo_lifecycle_service),
) -> RegisteredRepoRead:
    await service.switch_branch(repo, request.branch, current_user)
    return RegisteredRepoRead.model_validate(repo)
