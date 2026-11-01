"""
    The pull request review flow against the real local Postgres: what a fake session cannot show, namely the
    job's new columns, the release query, the stored files and a real concurrent submit.

    Commits real rows through separate connections and deletes them at the end. Requires the migrations to have
    been applied (`alembic upgrade head`).
"""
import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from api.config.settings import get_api_settings
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.db.models.review_job_file import ReviewJobFile
from api.db.models.user import User
from api.repos.repository import RegisteredRepoRepository
from api.review.errors import TooManyUnfinishedReviewsError
from api.review.pull_request_files import FetchedPullRequestFiles
from api.review.pull_request_loader import PullRequestSubmissionLoader
from api.review.pull_request_release import INDEX_FAILED_REASON, PendingPullRequestReleaser
from api.review.pull_request_submission import (
    WAITING_FOR_INDEX_REASON,
    PullRequestSubmissionDependencies,
    PullRequestSubmissionService,
)
from api.review.review_capacity import ReviewSlotKeeper
from api.schemas.pull_requests import PullRequestReviewRequest
from code_reviewer.schemas.submission import SubmittedFile
from tests.api.review.test_pull_request_submission import (
    FakeGitHubClient,
    FakeLifecycleService,
    FakeProducer,
    FakeTokenCipher,
    _pull_request,
)

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

LIMIT = 3
USER_GITHUB_ID = 940_000_201
REPO_ID = 940_100_001
OTHER_REPO_ID = 940_100_002
PR_URL = "https://github.com/slot-test/repo/pull/7"


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    test_engine = create_async_engine(get_api_settings().async_database_url, pool_size=14)
    yield test_engine
    async with async_sessionmaker(test_engine)() as cleanup_session:
        test_user_ids = select(User.id).where(User.github_id == USER_GITHUB_ID)
        await cleanup_session.execute(delete(ReviewJob).where(ReviewJob.requested_by_user_id.in_(test_user_ids)))
        await cleanup_session.execute(delete(RegisteredRepo).where(RegisteredRepo.repo_id.in_((REPO_ID, OTHER_REPO_ID))))
        await cleanup_session.execute(delete(User).where(User.github_id == USER_GITHUB_ID))
        await cleanup_session.commit()
    await test_engine.dispose()


async def _create_user(engine: AsyncEngine) -> User:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        user = User(
            github_id=USER_GITHUB_ID,
            github_username="pr-flow-test",
            encrypted_github_token="secret",
            github_granted_scopes="repo",
        )
        session.add(user)
        await session.commit()
        return user


async def _create_repo(
    engine: AsyncEngine, user: User, repo_id: int = REPO_ID, status: RepoIndexStatus = RepoIndexStatus.COMPLETED
) -> RegisteredRepo:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        repo = RegisteredRepo(
            repo_id=repo_id,
            owner_id=99,
            full_name=f"slot-test/repo-{repo_id}",
            default_branch="main",
            branch="main",
            commit_sha="indexed-sha",
            registered_by_user_id=user.id,
            status=status,
        )
        session.add(repo)
        await session.commit()
        return repo


def _job(user: User, repo_id: int | None, status: ReviewJobStatus, pr_number: int | None) -> ReviewJob:
    return ReviewJob(
        review_id=uuid.uuid4(),
        repo_id=repo_id,
        requested_by_user_id=user.id,
        file_paths=[],
        pr_number=pr_number,
        head_sha="head-sha" if pr_number else None,
        status=status,
        status_reason=WAITING_FOR_INDEX_REASON if status == ReviewJobStatus.PENDING and pr_number else None,
    )


async def _store(engine: AsyncEngine, jobs: list[ReviewJob]) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        session.add_all(jobs)
        await session.commit()


async def _reload(engine: AsyncEngine, review_id: uuid.UUID) -> ReviewJob:
    async with async_sessionmaker(engine)() as session:
        return await session.scalar(select(ReviewJob).where(ReviewJob.review_id == review_id))


def _service(session: AsyncSession, repo: RegisteredRepo, producer: FakeProducer, base_repo_id: int):
    return PullRequestSubmissionService(
        PullRequestSubmissionDependencies(
            github_client=FakeGitHubClient(_pull_request(base_repo_id=base_repo_id)),
            token_cipher=FakeTokenCipher(),
            repository=RegisteredRepoRepository(session),
            lifecycle_service=FakeLifecycleService(repo),
            producer=producer,
            session=session,
            slot_keeper=ReviewSlotKeeper(session, LIMIT),
            max_changed_files=100,
        )
    )


async def _submit_in_own_session(engine: AsyncEngine, user: User, repo: RegisteredRepo, barrier: asyncio.Barrier) -> bool:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        service = _service(session, repo, FakeProducer(), repo.repo_id)
        await barrier.wait()
        try:
            await service.submit(PullRequestReviewRequest(pr_url=PR_URL), user)
        except TooManyUnfinishedReviewsError:
            return False
        return True


async def test_a_submitted_pull_request_job_keeps_its_number_and_head_commit(engine: AsyncEngine) -> None:
    """Verify the columns added for pull requests survive a round trip through Postgres."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        job = await _service(session, repo, FakeProducer(), REPO_ID).submit(PullRequestReviewRequest(pr_url=PR_URL), user)

    stored = await _reload(engine, job.review_id)

    assert (stored.pr_number, stored.head_sha, stored.repo_id, stored.status) == (
        7,
        "head-sha",
        REPO_ID,
        ReviewJobStatus.PENDING,
    )


async def test_a_pull_request_for_an_indexing_repo_is_stored_waiting_and_not_published(engine: AsyncEngine) -> None:
    """Verify the waiting reason is persisted and nothing is sent to the worker yet."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user, status=RepoIndexStatus.INDEXING)
    producer = FakeProducer()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        job = await _service(session, repo, producer, REPO_ID).submit(PullRequestReviewRequest(pr_url=PR_URL), user)

    stored = await _reload(engine, job.review_id)

    assert (stored.status_reason, producer.published) == (WAITING_FOR_INDEX_REASON, [])


async def test_a_user_at_the_limit_cannot_submit_another_pull_request(engine: AsyncEngine) -> None:
    """Verify the cap holds on the pull request path against real rows, and a refused submit stores nothing."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    await _store(engine, [_job(user, REPO_ID, ReviewJobStatus.PENDING, 1 + number) for number in range(LIMIT)])

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        with pytest.raises(TooManyUnfinishedReviewsError):
            await _service(session, repo, FakeProducer(), REPO_ID).submit(PullRequestReviewRequest(pr_url=PR_URL), user)

    async with async_sessionmaker(engine)() as session:
        stored = await session.scalar(select(func.count()).select_from(ReviewJob).where(ReviewJob.requested_by_user_id == user.id))
    assert stored == LIMIT


async def test_simultaneous_pull_request_submissions_from_one_user_never_exceed_the_limit(engine: AsyncEngine) -> None:
    """Verify the whole submit path, not just the keeper, is safe when a user submits many pull requests at once."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    barrier = asyncio.Barrier(10)

    results = await asyncio.gather(*(_submit_in_own_session(engine, user, repo, barrier) for _ in range(10)))

    assert results.count(True) == LIMIT


async def test_release_publishes_only_the_pending_pull_request_jobs_of_that_repo(engine: AsyncEngine) -> None:
    """Verify the release query against the real enum and the nullable pr_number column."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    await _create_repo(engine, user, OTHER_REPO_ID)
    waiting = _job(user, REPO_ID, ReviewJobStatus.PENDING, 7)
    ignored = [
        _job(user, REPO_ID, ReviewJobStatus.RUNNING, 8),
        _job(user, REPO_ID, ReviewJobStatus.COMPLETED, 9),
        _job(user, REPO_ID, ReviewJobStatus.PENDING, None),
        _job(user, OTHER_REPO_ID, ReviewJobStatus.PENDING, 10),
    ]
    await _store(engine, [waiting, *ignored])
    producer = FakeProducer()

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await PendingPullRequestReleaser(producer).release(repo, session)

    assert [message.review_id for _topic, message, _key in producer.published] == [waiting.review_id]


async def test_release_clears_the_waiting_reason_in_the_database(engine: AsyncEngine) -> None:
    """Verify the reason is gone for a poller once the review has been handed to the worker."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    waiting = _job(user, REPO_ID, ReviewJobStatus.PENDING, 7)
    await _store(engine, [waiting])

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await PendingPullRequestReleaser(FakeProducer()).release(repo, session)

    assert (await _reload(engine, waiting.review_id)).status_reason is None


async def test_fail_marks_only_the_waiting_pull_request_jobs_of_that_repo_failed(engine: AsyncEngine) -> None:
    """Verify a repo that could not be indexed fails its waiting reviews and leaves everything else alone."""
    user = await _create_user(engine)
    await _create_repo(engine, user)
    await _create_repo(engine, user, OTHER_REPO_ID)
    waiting = _job(user, REPO_ID, ReviewJobStatus.PENDING, 7)
    running = _job(user, REPO_ID, ReviewJobStatus.RUNNING, 8)
    other_repo = _job(user, OTHER_REPO_ID, ReviewJobStatus.PENDING, 9)
    await _store(engine, [waiting, running, other_repo])

    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await PendingPullRequestReleaser(FakeProducer()).fail(REPO_ID, session)

    after = [await _reload(engine, job.review_id) for job in (waiting, running, other_repo)]
    assert [(job.status, job.status_reason) for job in after] == [
        (ReviewJobStatus.FAILED, INDEX_FAILED_REASON),
        (ReviewJobStatus.RUNNING, None),
        (ReviewJobStatus.PENDING, WAITING_FOR_INDEX_REASON),
    ]


class StubFetcher:
    def __init__(self, files: list[SubmittedFile]) -> None:
        self._files = files

    async def fetch(self, access_token: str, source) -> FetchedPullRequestFiles:
        return FetchedPullRequestFiles(files=self._files, skipped=[])


async def _load_files(engine: AsyncEngine, user: User, repo: RegisteredRepo, job_id: uuid.UUID, files: list[SubmittedFile]) -> None:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        job = await session.scalar(select(ReviewJob).where(ReviewJob.review_id == job_id))
        loader = PullRequestSubmissionLoader(StubFetcher(files), FakeTokenCipher())
        await loader.load(job, repo, session)


async def _stored_files(engine: AsyncEngine, job_id: uuid.UUID) -> list[tuple[str, str]]:
    async with async_sessionmaker(engine)() as session:
        job = await session.scalar(select(ReviewJob).where(ReviewJob.review_id == job_id))
        rows = await session.scalars(select(ReviewJobFile).where(ReviewJobFile.review_job_id == job.id).order_by(ReviewJobFile.file_path))
        return [(row.file_path, row.content) for row in rows]


async def test_loading_a_pull_request_stores_its_files_on_the_job(engine: AsyncEngine) -> None:
    """Verify the pull request's source is kept in review_job_files, ready for the annotated view."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    job = _job(user, REPO_ID, ReviewJobStatus.RUNNING, 7)
    await _store(engine, [job])

    await _load_files(engine, user, repo, job.review_id, [SubmittedFile(file_path="a.py", content="x = 1\n")])

    assert await _stored_files(engine, job.review_id) == [("a.py", "x = 1\n")]


async def test_loading_a_pull_request_again_replaces_the_files_instead_of_colliding(engine: AsyncEngine) -> None:
    """Verify a review run again after a crash does not hit the unique (job, path) constraint."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    job = _job(user, REPO_ID, ReviewJobStatus.RUNNING, 7)
    await _store(engine, [job])
    await _load_files(engine, user, repo, job.review_id, [SubmittedFile(file_path="a.py", content="old\n")])

    await _load_files(engine, user, repo, job.review_id, [SubmittedFile(file_path="a.py", content="new\n")])

    assert await _stored_files(engine, job.review_id) == [("a.py", "new\n")]


async def test_loading_a_pull_request_records_the_file_list_on_the_job(engine: AsyncEngine) -> None:
    """Verify the job's file list, empty at submit, is filled in and persisted for a poller."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    job = _job(user, REPO_ID, ReviewJobStatus.RUNNING, 7)
    await _store(engine, [job])

    await _load_files(engine, user, repo, job.review_id, [SubmittedFile(file_path="a.py", content="x\n"), SubmittedFile(file_path="b.py", content="y\n")])

    assert (await _reload(engine, job.review_id)).file_paths == ["a.py", "b.py"]


async def test_deleting_a_review_job_deletes_its_stored_files(engine: AsyncEngine) -> None:
    """Verify, after the table rename, that the cascade from the job to its files still works."""
    user = await _create_user(engine)
    repo = await _create_repo(engine, user)
    job = _job(user, REPO_ID, ReviewJobStatus.RUNNING, 7)
    await _store(engine, [job])
    await _load_files(engine, user, repo, job.review_id, [SubmittedFile(file_path="a.py", content="x\n")])

    async with async_sessionmaker(engine)() as session:
        job_row_id = await session.scalar(select(ReviewJob.id).where(ReviewJob.review_id == job.review_id))
        await session.execute(delete(ReviewJob).where(ReviewJob.review_id == job.review_id))
        await session.commit()
        remaining = await session.scalar(
            select(func.count()).select_from(ReviewJobFile).where(ReviewJobFile.review_job_id == job_row_id)
        )

    assert remaining == 0
