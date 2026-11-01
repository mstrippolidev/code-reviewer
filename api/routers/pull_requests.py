from fastapi import APIRouter, Depends, status

from api.db.models.user import User
from api.dependencies import get_current_user
from api.review.pull_request_dependencies import get_pull_request_submission_service
from api.review.review_capacity import require_review_capacity
from api.review.pull_request_submission import PullRequestSubmissionService
from api.schemas.pull_requests import PullRequestReviewRequest
from api.schemas.reviews import ReviewJobRead
from api.security.rate_limit_dependencies import limit_review_submissions

router = APIRouter(prefix="/api/pull-requests", tags=["Pull requests"])


@router.post(
    "/review",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_review_submissions), Depends(require_review_capacity)],
)
async def submit_pull_request_review(
    request: PullRequestReviewRequest,
    current_user: User = Depends(get_current_user),
    service: PullRequestSubmissionService = Depends(get_pull_request_submission_service),
) -> ReviewJobRead:
    """Queues a review of the pull request at the URL and returns at once; poll the review for the report.

    If the pull request's repo is not indexed yet, it is registered and indexed first, and the review stays
    `pending` until that finishes.
    """
    job = await service.submit(request, current_user)
    return ReviewJobRead.model_validate(job)
