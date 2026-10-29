"""
    Tests for RegisteredRepoRepository.count_active_indexing against the real local Postgres, inside a
    rolled-back transaction.

    Requires the migrations to have been applied (`alembic upgrade head`).
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.repos.repository import RegisteredRepoRepository

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

OWNER_GITHUB_ID = 970_000_001
OTHER_OWNER_GITHUB_ID = 970_000_002
FIRST_REPO_ID = 970_000_101


async def _add_user(session: AsyncSession, github_id: int) -> User:
    user = User(
        github_id=github_id,
        github_username=f"user-{github_id}",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    await session.flush()
    return user


async def _add_repo(session: AsyncSession, owner: User, repo_id: int, status: RepoIndexStatus) -> None:
    session.add(
        RegisteredRepo(
            repo_id=repo_id,
            owner_id=1,
            full_name=f"octocat/repo-{repo_id}",
            default_branch="main",
            branch="main",
            registered_by_user_id=owner.id,
            status=status,
        )
    )
    await session.flush()


async def test_only_pending_and_indexing_repos_of_the_owner_are_counted(async_session: AsyncSession) -> None:
    owner = await _add_user(async_session, OWNER_GITHUB_ID)
    other_owner = await _add_user(async_session, OTHER_OWNER_GITHUB_ID)
    statuses = [
        RepoIndexStatus.PENDING,
        RepoIndexStatus.INDEXING,
        RepoIndexStatus.PAUSED,
        RepoIndexStatus.COMPLETED,
        RepoIndexStatus.FAILED,
    ]
    for offset, status in enumerate(statuses):
        await _add_repo(async_session, owner, FIRST_REPO_ID + offset, status)
    await _add_repo(async_session, other_owner, FIRST_REPO_ID + 50, RepoIndexStatus.INDEXING)

    count = await RegisteredRepoRepository(async_session).count_active_indexing(owner.id, excluding_repo_id=0)

    assert count == 2


async def test_the_excluded_repo_is_not_counted(async_session: AsyncSession) -> None:
    owner = await _add_user(async_session, OWNER_GITHUB_ID)
    await _add_repo(async_session, owner, FIRST_REPO_ID, RepoIndexStatus.INDEXING)
    await _add_repo(async_session, owner, FIRST_REPO_ID + 1, RepoIndexStatus.INDEXING)

    count = await RegisteredRepoRepository(async_session).count_active_indexing(owner.id, FIRST_REPO_ID)

    assert count == 1


async def test_an_owner_with_no_repos_has_none_unfinished(async_session: AsyncSession) -> None:
    owner = await _add_user(async_session, OWNER_GITHUB_ID)

    assert await RegisteredRepoRepository(async_session).count_active_indexing(owner.id, excluding_repo_id=0) == 0
