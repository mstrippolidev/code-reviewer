from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.review_job import ReviewJob
from api.dependencies import get_caller_ids, get_db_session, require_review_access
from api.feedback.errors import IncidentNotFoundError
from api.feedback.rater import CallerIds, rater_for
from api.feedback.service import FeedbackService
from api.schemas.feedback import FeedbackRead, FeedbackWrite

router = APIRouter(prefix="/api", tags=["Feedback"])


def get_feedback_service(session: AsyncSession = Depends(get_db_session)) -> FeedbackService:
    return FeedbackService(session)


@router.put("/reviews/{review_id}/feedback")
async def rate_incident(
    write: FeedbackWrite,
    job: ReviewJob = Depends(require_review_access),
    caller: CallerIds = Depends(get_caller_ids),
    service: FeedbackService = Depends(get_feedback_service),
) -> FeedbackRead:
    """Stores the caller's thumbs up or down on one incident of this review, replacing an earlier rating."""
    try:
        return await service.submit(job, rater_for(job, caller), write)
    except IncidentNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found in this review") from error


@router.get("/reviews/{review_id}/feedback")
async def list_my_feedback(
    job: ReviewJob = Depends(require_review_access),
    caller: CallerIds = Depends(get_caller_ids),
    service: FeedbackService = Depends(get_feedback_service),
) -> list[FeedbackRead]:
    """The caller's own ratings on this review, so a page can show them after a reload."""
    return await service.list_for(job, rater_for(job, caller))
