"""
    Queues a pull request review for the worker; shared by the submit route and by the release of reviews
    that waited for their repo to finish indexing.
"""
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.review_job import ReviewJob
from api.indexing.producer import RepoIndexProducer
from api.review.topics import REVIEW_REQUESTED
from api.schemas.reviews import ReviewRequestedMessage

NOT_QUEUED_REASON = "Could not queue this review"


def build_pull_request_message(job: ReviewJob, repo: RegisteredRepo) -> ReviewRequestedMessage:
    """The review.requested message for a pull request job; it carries no files, the worker reads them from GitHub."""
    return ReviewRequestedMessage(
        review_id=job.review_id,
        file_paths=[],
        agents=job.agents,
        repo_id=repo.repo_id,
        owner_id=repo.owner_id,
        requested_by_user_id=job.requested_by_user_id,
        pr_number=job.pr_number,
    )


async def publish_pull_request_review(producer: RepoIndexProducer, job: ReviewJob, repo: RegisteredRepo) -> None:
    """Sends the job to the worker, keyed by its review id.

    Raises:
        PublishError: If Kafka refuses the message.
    """
    message = build_pull_request_message(job, repo)
    await producer.publish(REVIEW_REQUESTED, message, str(job.review_id).encode())
