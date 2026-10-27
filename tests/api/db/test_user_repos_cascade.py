"""
    Tests for the user_repos constraints against the real local Postgres.

    Every test runs inside a transaction that is rolled back at the end, so nothing is persisted.
    Requires the migrations to have been applied (`alembic upgrade head`).
"""
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.config.settings import get_api_settings
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user import User
from api.db.models.user_repo import UserRepo

pytestmark = pytest.mark.db

FIRST_USER_GITHUB_ID = 910_000_001
SECOND_USER_GITHUB_ID = 910_000_002
FIRST_REPO_ID = 910_000_101
SECOND_REPO_ID = 910_000_102


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(get_api_settings().sync_database_url)
    connection = engine.connect()
    transaction = connection.begin()
    test_session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield test_session

    test_session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


def _add_user(session: Session, github_id: int) -> User:
    user = User(
        github_id=github_id,
        github_username=f"user-{github_id}",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    session.flush()
    return user


def _add_repo(session: Session, repo_id: int, owner: User) -> RegisteredRepo:
    repo = RegisteredRepo(
        repo_id=repo_id,
        owner_id=1,
        full_name=f"octocat/repo-{repo_id}",
        default_branch="main",
        branch="main",
        registered_by_user_id=owner.id,
    )
    session.add(repo)
    session.flush()
    return repo


def _link(session: Session, user: User, repo: RegisteredRepo) -> None:
    session.add(UserRepo(user_id=user.id, repo_id=repo.repo_id))
    session.flush()


def _link_count(session: Session, **filters: int) -> int:
    statement = select(func.count()).select_from(UserRepo).filter_by(**filters)
    return session.scalar(statement)


def test_two_users_can_be_linked_to_the_same_repo(session: Session) -> None:
    """Verify that the schema allows several users to share one registered repo."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    other = _add_user(session, SECOND_USER_GITHUB_ID)
    repo = _add_repo(session, FIRST_REPO_ID, owner)

    _link(session, owner, repo)
    _link(session, other, repo)

    assert _link_count(session, repo_id=FIRST_REPO_ID) == 2


def test_deleting_a_repo_removes_every_link_to_it(session: Session) -> None:
    """Verify that deleting a repo also removes the links of all the users in it."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    other = _add_user(session, SECOND_USER_GITHUB_ID)
    repo = _add_repo(session, FIRST_REPO_ID, owner)
    _link(session, owner, repo)
    _link(session, other, repo)

    session.execute(delete(RegisteredRepo).where(RegisteredRepo.repo_id == FIRST_REPO_ID))

    assert _link_count(session, repo_id=FIRST_REPO_ID) == 0


def test_deleting_a_repo_keeps_the_links_to_other_repos(session: Session) -> None:
    """Verify that the cascade only follows the deleted repo."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    deleted = _add_repo(session, FIRST_REPO_ID, owner)
    kept = _add_repo(session, SECOND_REPO_ID, owner)
    _link(session, owner, deleted)
    _link(session, owner, kept)

    session.execute(delete(RegisteredRepo).where(RegisteredRepo.repo_id == FIRST_REPO_ID))

    assert _link_count(session, repo_id=SECOND_REPO_ID) == 1


def test_deleting_a_user_removes_their_links(session: Session) -> None:
    """Verify that a deleted account leaves no links behind."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    other = _add_user(session, SECOND_USER_GITHUB_ID)
    repo = _add_repo(session, FIRST_REPO_ID, owner)
    _link(session, other, repo)
    other_id = other.id

    session.execute(delete(User).where(User.id == other_id))

    assert _link_count(session, user_id=other_id) == 0


def test_deleting_a_user_keeps_the_links_of_other_users(session: Session) -> None:
    """Verify that removing one account does not unlink the owner from the shared repo."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    other = _add_user(session, SECOND_USER_GITHUB_ID)
    repo = _add_repo(session, FIRST_REPO_ID, owner)
    _link(session, owner, repo)
    _link(session, other, repo)

    session.execute(delete(User).where(User.id == other.id))

    assert _link_count(session, repo_id=FIRST_REPO_ID) == 1


def test_linking_the_same_user_to_the_same_repo_twice_is_rejected(session: Session) -> None:
    """Verify that the unique constraint stops a duplicate link, even if two requests race."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)
    repo = _add_repo(session, FIRST_REPO_ID, owner)
    _link(session, owner, repo)

    with pytest.raises(IntegrityError):
        _link(session, owner, repo)


def test_linking_a_user_to_a_repo_that_does_not_exist_is_rejected(session: Session) -> None:
    """Verify that a link cannot point at a repo that was never registered."""
    owner = _add_user(session, FIRST_USER_GITHUB_ID)

    with pytest.raises(IntegrityError):
        session.add(UserRepo(user_id=owner.id, repo_id=FIRST_REPO_ID))
        session.flush()
