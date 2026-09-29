import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.models.guest_review_file import GuestReviewFile
from api.db.models.guest_session import GuestSession
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.dependencies import (
    GUEST_SESSION_COOKIE,
    get_db_session,
    get_guest_session,
    get_jwt_service,
    get_kafka_producer,
)
from api.indexing.producer import PublishError, RepoIndexProducer
from api.review.topics import REVIEW_REQUESTED
from api.schemas.reviews import GuestReviewSubmissionRequest, ReviewJobRead, ReviewRequestedMessage
from api.security.jwt_service import JwtTokenService

router = APIRouter(prefix="/api/guest", tags=["Guest"])


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
async def start_guest_session(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
) -> None:
    guest_session = GuestSession()
    session.add(guest_session)
    await session.commit()
    await session.refresh(guest_session)
    settings = get_api_settings()
    response.set_cookie(
        key=GUEST_SESSION_COOKIE,
        value=jwt_service.issue_guest_session_token(guest_session_id=guest_session.id),
        max_age=settings.api_jwt_access_token_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.api_environment != "local",
    )


@router.post("/review", status_code=status.HTTP_202_ACCEPTED)
async def submit_guest_review(
    request: GuestReviewSubmissionRequest,
    guest_session: GuestSession = Depends(get_guest_session),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
) -> ReviewJobRead:
    job = ReviewJob(
        review_id=uuid.uuid4(),
        guest_session_id=guest_session.id,
        file_paths=[file.file_path for file in request.files],
        status=ReviewJobStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    for file in request.files:
        session.add(GuestReviewFile(review_job_id=job.id, file_path=file.file_path, content=file.content))
    await session.commit()
    await session.refresh(job)
    await _publish_guest_review_requested(job, kafka_producer)
    return ReviewJobRead.model_validate(job)


async def _publish_guest_review_requested(job: ReviewJob, kafka_producer: RepoIndexProducer) -> None:
    message = ReviewRequestedMessage(
        review_id=job.review_id,
        file_paths=job.file_paths,
        guest_session_id=job.guest_session_id,
    )
    try:
        await kafka_producer.publish(REVIEW_REQUESTED, message, str(job.review_id).encode())
    except PublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not queue this review",
        ) from error
