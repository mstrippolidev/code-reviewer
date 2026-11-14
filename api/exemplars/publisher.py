"""
    Queues the files a finished repo review rated 100, so the judge panel can consider them as exemplars.
"""
import logging

from api.db.models.review_job import ReviewJob
from api.exemplars.candidates import perfect_file_nominations
from api.exemplars.topics import EXEMPLAR_PROMOTION_REQUESTED
from api.indexing.producer import RepoIndexProducer
from api.schemas.exemplars import ExemplarPromotionRequestedMessage

logger = logging.getLogger(__name__)


class ExemplarNominationPublisher:
    """Publishes one promotion request per perfect-rated file and agent of a finished review."""

    def __init__(self, producer: RepoIndexProducer) -> None:
        self._producer = producer

    async def nominate(self, job: ReviewJob) -> None:
        """Queues the job's nominations; a failure is only logged, since the review itself already finished."""
        try:
            for file_path, code_key in perfect_file_nominations(job.agent_entries or {}):
                message = ExemplarPromotionRequestedMessage(
                    review_id=job.review_id, repo_id=job.repo_id, file_path=file_path, code_key=code_key
                )
                await self._producer.publish(EXEMPLAR_PROMOTION_REQUESTED, message, str(job.repo_id).encode())
        except Exception:
            logger.exception("Could not queue exemplar nominations for review_id=%s", job.review_id)
