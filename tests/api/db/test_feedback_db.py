"""
    The incident recorder and the feedback service against the real local Postgres, inside a rolled-back transaction.
    Requires the migrations to have been applied (`alembic upgrade head`); the tests only add rows.
"""
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.finding_feedback import FeedbackReason, FeedbackVerdict, FindingFeedback
from api.db.models.review_incident import ReviewIncident
from api.db.models.review_job import ReviewJob
from api.db.models.user import User
from api.feedback.errors import IncidentNotFoundError
from api.feedback.incident_recorder import IncidentRecorder
from api.feedback.rater import Rater
from api.feedback.service import FeedbackService
from api.schemas.feedback import FeedbackWrite

pytestmark = [pytest.mark.db, pytest.mark.asyncio]


def _incident(description: str) -> dict:
    return {"priority": "high", "line_position": "1-2", "description": description, "advice": "fix it"}


async def _user(session: AsyncSession, github_id: int) -> User:
    user = User(
        github_id=github_id,
        github_username=f"feedback-test-{github_id}",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    await session.flush()
    return user


async def _job(session: AsyncSession, user: User) -> ReviewJob:
    job = ReviewJob(review_id=uuid.uuid4(), requested_by_user_id=user.id, file_paths=["a.py"])
    session.add(job)
    await session.flush()
    return job


async def _incident_id(session: AsyncSession, job: ReviewJob, description: str = "mixed concerns") -> int:
    entry = {"code_key": "SOLID1", "incidents": [_incident(description)]}
    stamped = await IncidentRecorder(session).stamp_entry(job.id, "a.py", entry)
    return stamped["incidents"][0]["incident_id"]


async def test_recording_the_same_incident_again_returns_the_same_id(async_session: AsyncSession) -> None:
    job = await _job(async_session, await _user(async_session, 940_000_301))

    first = await _incident_id(async_session, job)
    second = await _incident_id(async_session, job)

    assert first == second
    stored = await async_session.scalar(select(func.count()).select_from(ReviewIncident).where(ReviewIncident.review_job_id == job.id))
    assert stored == 1


async def test_a_different_incident_gets_a_different_id(async_session: AsyncSession) -> None:
    job = await _job(async_session, await _user(async_session, 940_000_302))

    assert await _incident_id(async_session, job, "one") != await _incident_id(async_session, job, "two")


async def test_the_merged_result_reuses_the_id_of_the_agents_incident(async_session: AsyncSession) -> None:
    job = await _job(async_session, await _user(async_session, 940_000_303))
    agent_id = await _incident_id(async_session, job)
    result = {"review": [{"file_path": "a.py", "incidents": [{**_incident("mixed concerns"), "code_key": "SOLID1"}]}]}

    stamped = await IncidentRecorder(async_session).stamp_result(job.id, result)

    assert stamped["review"][0]["incidents"][0]["incident_id"] == agent_id


async def test_rating_twice_keeps_one_row_that_holds_the_latest_rating(async_session: AsyncSession) -> None:
    user = await _user(async_session, 940_000_304)
    job = await _job(async_session, user)
    incident_id = await _incident_id(async_session, job)
    service = FeedbackService(async_session)

    await service.submit(job, Rater(user_id=user.id), FeedbackWrite(incident_id=incident_id, verdict=FeedbackVerdict.UP))
    changed = FeedbackWrite(incident_id=incident_id, verdict=FeedbackVerdict.DOWN, reason=FeedbackReason.NOT_TRUE)
    await service.submit(job, Rater(user_id=user.id), changed)

    mine = await service.list_for(job, Rater(user_id=user.id))
    assert [(rating.verdict, rating.reason) for rating in mine] == [(FeedbackVerdict.DOWN, FeedbackReason.NOT_TRUE)]


async def test_two_raters_of_one_incident_are_two_ratings(async_session: AsyncSession) -> None:
    user = await _user(async_session, 940_000_305)
    other = await _user(async_session, 940_000_306)
    job = await _job(async_session, user)
    incident_id = await _incident_id(async_session, job)
    service = FeedbackService(async_session)
    write = FeedbackWrite(incident_id=incident_id, verdict=FeedbackVerdict.UP)

    await service.submit(job, Rater(user_id=user.id), write)
    await service.submit(job, Rater(user_id=other.id), write)

    stored = await async_session.scalar(select(func.count()).select_from(FindingFeedback).where(FindingFeedback.incident_id == incident_id))
    assert stored == 2
    assert len(await service.list_for(job, Rater(user_id=user.id))) == 1


async def test_an_incident_of_another_review_cannot_be_rated(async_session: AsyncSession) -> None:
    user = await _user(async_session, 940_000_307)
    job = await _job(async_session, user)
    other_job = await _job(async_session, user)
    foreign_incident_id = await _incident_id(async_session, other_job)

    with pytest.raises(IncidentNotFoundError):
        await FeedbackService(async_session).submit(
            job, Rater(user_id=user.id), FeedbackWrite(incident_id=foreign_incident_id, verdict=FeedbackVerdict.UP)
        )


async def test_deleting_a_review_deletes_its_incidents_and_their_ratings(async_session: AsyncSession) -> None:
    user = await _user(async_session, 940_000_308)
    job = await _job(async_session, user)
    incident_id = await _incident_id(async_session, job)
    await FeedbackService(async_session).submit(
        job, Rater(user_id=user.id), FeedbackWrite(incident_id=incident_id, verdict=FeedbackVerdict.UP)
    )

    await async_session.delete(job)
    await async_session.flush()

    left = await async_session.scalar(select(func.count()).select_from(FindingFeedback).where(FindingFeedback.incident_id == incident_id))
    assert left == 0
