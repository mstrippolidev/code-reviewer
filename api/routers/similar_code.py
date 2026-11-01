import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.similar_code_search import SimilarCodeSearch, SimilarCodeSearchStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session, get_kafka_producer, require_github_repo_access
from api.indexing.producer import PublishError, RepoIndexProducer
from api.schemas.similar_code import SimilarCodeRequest, SimilarCodeRequestedMessage, SimilarCodeSearchRead
from api.security.rate_limit_dependencies import limit_similar_code_searches
from api.similar_code.topics import SIMILAR_CODE_REQUESTED

router = APIRouter(prefix="/api", tags=["Similar code"])

SEARCH_NOT_QUEUED_DETAIL = "Could not queue this search"


@router.post(
    "/repos/{repo_id}/similar-code",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_similar_code_searches)],
)
async def submit_similar_code_search(
    request: SimilarCodeRequest,
    repo: RegisteredRepo = Depends(require_github_repo_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
) -> SimilarCodeSearchRead:
    """Queues a check of the snippet against the repo's indexed history and returns at once; poll the search for the answer."""
    if repo.status != RepoIndexStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Repo is not fully indexed yet")
    search = SimilarCodeSearch(
        search_id=uuid.uuid4(), repo_id=repo.repo_id, requested_by_user_id=current_user.id, code=request.code
    )
    session.add(search)
    await session.commit()
    await session.refresh(search)
    await _publish_requested(search, kafka_producer, session)
    return SimilarCodeSearchRead.model_validate(search)


@router.get("/similar-code/{search_id}")
async def get_similar_code_search(
    search_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> SimilarCodeSearchRead:
    """Progress and, once finished, the result of a search; only the user who asked can read it."""
    search = await session.scalar(
        select(SimilarCodeSearch).where(
            SimilarCodeSearch.search_id == search_id,
            SimilarCodeSearch.requested_by_user_id == current_user.id,
        )
    )
    if search is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Search {search_id} was not found")
    return SimilarCodeSearchRead.model_validate(search)


async def _publish_requested(
    search: SimilarCodeSearch, kafka_producer: RepoIndexProducer, session: AsyncSession
) -> None:
    """Sends the search to the worker; if Kafka refuses it, fails the search and deletes the stored snippet instead of leaving it queued forever."""
    message = SimilarCodeRequestedMessage(search_id=search.search_id, repo_id=search.repo_id)
    try:
        await kafka_producer.publish(SIMILAR_CODE_REQUESTED, message, str(search.search_id).encode())
    except PublishError as error:
        search.status = SimilarCodeSearchStatus.FAILED
        search.status_reason = SEARCH_NOT_QUEUED_DETAIL
        search.code = None
        await session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=SEARCH_NOT_QUEUED_DETAIL) from error
