"""
    Stores a rater's thumbs up or down on an incident of a review, and reads a rater's ratings back.
"""
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.finding_feedback import FindingFeedback
from api.db.models.review_incident import ReviewIncident
from api.db.models.review_job import ReviewJob
from api.feedback.errors import IncidentNotFoundError
from api.feedback.rater import Rater
from api.observability.metrics import api_metrics
from api.schemas.feedback import FeedbackRead, FeedbackWrite

RATER_CONSTRAINT = "uq_finding_feedback_incident_rater"


class FeedbackService:
    """Keeps one rating per rater and incident; rating again replaces it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def submit(self, job: ReviewJob, rater: Rater, write: FeedbackWrite) -> FeedbackRead:
        """Stores the rating of an incident that belongs to this review.

        Raises:
            IncidentNotFoundError: If the review has no incident with that id.
        """
        incident = await self._session.scalar(
            select(ReviewIncident).where(ReviewIncident.id == write.incident_id, ReviewIncident.review_job_id == job.id)
        )
        if incident is None:
            raise IncidentNotFoundError(f"Review {job.review_id} has no incident {write.incident_id}.")
        rating = {"verdict": write.verdict, "reason": write.reason, "note": write.note}
        statement = insert(FindingFeedback).values(
            incident_id=incident.id,
            rater_key=rater.key,
            user_id=rater.user_id,
            guest_session_id=rater.guest_session_id,
            **rating,
        )
        await self._session.execute(
            statement.on_conflict_do_update(constraint=RATER_CONSTRAINT, set_={**rating, "updated_at": func.now()})
        )
        await self._session.commit()
        api_metrics.record_feedback(incident.code_key, write.verdict, write.reason)
        return FeedbackRead(incident_id=incident.id, **rating)

    async def list_for(self, job: ReviewJob, rater: Rater) -> list[FeedbackRead]:
        """Every rating this rater has given on this review."""
        rows = await self._session.scalars(
            select(FindingFeedback)
            .join(ReviewIncident, ReviewIncident.id == FindingFeedback.incident_id)
            .where(ReviewIncident.review_job_id == job.id, FindingFeedback.rater_key == rater.key)
            .order_by(FindingFeedback.incident_id)
        )
        return [FeedbackRead.model_validate(row) for row in rows]
