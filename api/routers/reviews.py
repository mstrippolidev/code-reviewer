import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import EventSourceResponse
from fastapi.sse import ServerSentEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.guest_review_file import GuestReviewFile
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_kafka_producer,
    require_github_repo_access,
    require_review_access,
    short_lived_db_session,
)
from api.indexing.producer import PublishError, RepoIndexProducer
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster
from api.review.topics import REVIEW_REQUESTED
from api.schemas.reviews import (
    RepolessReviewSubmissionRequest,
    ReviewAgentProgressMessage,
    ReviewFileContentRead,
    ReviewJobRead,
    ReviewRequestedMessage,
    ReviewStatusMessage,
    ReviewSubmissionRequest,
)
from api.security.rate_limit_dependencies import limit_review_submissions

router = APIRouter(prefix="/api", tags=["Reviews"])

_TERMINAL_JOB_STATUSES = frozenset({ReviewJobStatus.COMPLETED, ReviewJobStatus.FAILED})


@router.post(
    "/repos/{repo_id}/review",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_review_submissions)],
)
async def submit_review(
    request: ReviewSubmissionRequest,
    repo: RegisteredRepo = Depends(require_github_repo_access),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
) -> ReviewJobRead:
    await _require_files_are_indexed(repo.repo_id, request.file_paths, session)
    job = ReviewJob(
        review_id=uuid.uuid4(),
        repo_id=repo.repo_id,
        requested_by_user_id=current_user.id,
        file_paths=request.file_paths,
        agents=[agent.value for agent in request.agents] if request.agents else None,
        status=ReviewJobStatus.PENDING,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await _publish_review_requested(job, repo, kafka_producer)
    return ReviewJobRead.model_validate(job)


async def _require_files_are_indexed(repo_id: int, file_paths: list[str], session: AsyncSession) -> None:
    result = await session.scalars(
        select(IndexedFile.file_path).where(
            IndexedFile.repo_id == repo_id,
            IndexedFile.file_path.in_(file_paths),
            IndexedFile.status == IndexedFileStatus.INDEXED,
        )
    )
    indexed_paths = set(result.all())
    missing_paths = set(file_paths) - indexed_paths
    if missing_paths:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"These files are not indexed for this repo: {sorted(missing_paths)}",
        )


async def _publish_review_requested(job: ReviewJob, repo: RegisteredRepo, kafka_producer: RepoIndexProducer) -> None:
    message = ReviewRequestedMessage(
        review_id=job.review_id,
        repo_id=repo.repo_id,
        owner_id=repo.owner_id,
        requested_by_user_id=job.requested_by_user_id,
        file_paths=job.file_paths,
        agents=job.agents,
    )
    try:
        await kafka_producer.publish(REVIEW_REQUESTED, message, str(job.review_id).encode())
    except PublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not queue this review",
        ) from error


@router.post("/reviews", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(limit_review_submissions)])
async def submit_repoless_review(
    request: RepolessReviewSubmissionRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    kafka_producer: RepoIndexProducer = Depends(get_kafka_producer),
) -> ReviewJobRead:
    job = ReviewJob(
        review_id=uuid.uuid4(),
        requested_by_user_id=current_user.id,
        file_paths=[file.file_path for file in request.files],
        agents=[agent.value for agent in request.agents] if request.agents else None,
        status=ReviewJobStatus.PENDING,
    )
    session.add(job)
    await session.flush()
    for file in request.files:
        session.add(GuestReviewFile(review_job_id=job.id, file_path=file.file_path, content=file.content))
    await session.commit()
    await session.refresh(job)
    await _publish_repoless_review_requested(job, kafka_producer)
    return ReviewJobRead.model_validate(job)


async def _publish_repoless_review_requested(job: ReviewJob, kafka_producer: RepoIndexProducer) -> None:
    message = ReviewRequestedMessage(
        review_id=job.review_id,
        requested_by_user_id=job.requested_by_user_id,
        file_paths=job.file_paths,
        agents=job.agents,
    )
    try:
        await kafka_producer.publish(REVIEW_REQUESTED, message, str(job.review_id).encode())
    except PublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not queue this review",
        ) from error


@router.get("/reviews/{review_id}")
async def get_review(job: ReviewJob = Depends(require_review_access)) -> ReviewJobRead:
    return ReviewJobRead.model_validate(job)


@router.get("/reviews/{review_id}/files/content")
async def get_review_file_content(
    review_id: uuid.UUID,
    file_path: str,
    session: AsyncSession = Depends(get_db_session),
    job: ReviewJob = Depends(require_review_access),
) -> ReviewFileContentRead:
    """Serves a guest review's own submitted source; a repo review's source is served per repo instead."""
    guest_file = await session.scalar(
        select(GuestReviewFile).where(GuestReviewFile.review_job_id == job.id, GuestReviewFile.file_path == file_path)
    )
    if guest_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No submitted content for {file_path} in review {review_id}",
        )
    return ReviewFileContentRead.model_validate(guest_file)


async def _require_review_job(review_id: uuid.UUID, session: AsyncSession) -> ReviewJob:
    job = await session.scalar(select(ReviewJob).where(ReviewJob.review_id == review_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Review {review_id} was not found")
    return job


@router.get("/reviews/{review_id}/stream", response_class=EventSourceResponse)
async def stream_review(
    request: Request,
    review_id: uuid.UUID,
    _access_gate: ReviewJob = Depends(require_review_access),
) -> AsyncIterator[ServerSentEvent]:
    broadcaster: ReviewProgressBroadcaster = request.app.state.review_progress_broadcaster
    # Subscribing before reading the job closes the window where a review reaching a
    # terminal status between the two would publish to nobody, leaving this stream
    # backfilled with a stale status and then blocked on a queue that never fills again.
    queue = broadcaster.subscribe(review_id)
    try:
        async with short_lived_db_session(request) as session:
            job = await _require_review_job(review_id, session)
        yield ServerSentEvent(event="status", data=_current_job_status(job))
        if job.status in _TERMINAL_JOB_STATUSES:
            return
        while True:
            event = await queue.get()
            if isinstance(event, ReviewStatusMessage):
                yield ServerSentEvent(event="status", data=event)
                if event.status in _TERMINAL_JOB_STATUSES:
                    return
            elif isinstance(event, ReviewAgentProgressMessage):
                yield ServerSentEvent(event="agent", data=event)
            else:
                yield ServerSentEvent(event="file", data=event)
    finally:
        broadcaster.unsubscribe(review_id, queue)


def _current_job_status(job: ReviewJob) -> ReviewStatusMessage:
    return ReviewStatusMessage(
        review_id=job.review_id,
        repo_id=job.repo_id,
        status=job.status,
        status_reason=job.status_reason,
        file_paths=job.file_paths,
        result=job.result,
        agent_entries=job.agent_entries,
    )
