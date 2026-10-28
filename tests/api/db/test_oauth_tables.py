"""
    Tests for the OAuth tables' constraints and cascades against the real local Postgres.

    Every test runs inside a transaction that is rolled back at the end, so nothing is persisted.
    Requires the migrations to have been applied (`alembic upgrade head`).
"""
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.config.settings import get_api_settings
from api.db.models.oauth_client import OAuthClient
from api.db.models.oauth_consent import OAuthConsent
from api.db.models.oauth_token import OAuthToken
from api.db.models.user import User

pytestmark = pytest.mark.db

USER_GITHUB_ID = 920_000_001
CLIENT_ID = "test-client-920000001"
OTHER_CLIENT_ID = "test-client-920000002"


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


def _add_user(session: Session) -> User:
    user = User(
        github_id=USER_GITHUB_ID,
        github_username="oauth-test-user",
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )
    session.add(user)
    session.flush()
    return user


def _add_client(session: Session, client_id: str = CLIENT_ID) -> OAuthClient:
    client = OAuthClient(client_id=client_id, client_name="Test client", redirect_uris=["http://localhost:1/cb"])
    session.add(client)
    session.flush()
    return client


def _token(user: User, client: OAuthClient, suffix: str = "1") -> OAuthToken:
    now = datetime.utcnow()
    return OAuthToken(
        access_token_hash=f"access-hash-{suffix}",
        access_expires_at=now + timedelta(hours=1),
        refresh_token_hash=f"refresh-hash-{suffix}",
        refresh_expires_at=now + timedelta(days=7),
        family_id=uuid.uuid4(),
        authorized_at=now,
        user_id=user.id,
        client_id=client.client_id,
    )


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_a_client_keeps_its_redirect_uris_as_a_list(session: Session) -> None:
    client = _add_client(session)
    session.expire(client)

    assert session.get(OAuthClient, CLIENT_ID).redirect_uris == ["http://localhost:1/cb"]


def test_a_new_token_is_neither_used_nor_revoked(session: Session) -> None:
    token = _token(_add_user(session), _add_client(session))
    session.add(token)
    session.flush()

    assert token.refresh_used_at is None
    assert token.revoked_at is None


@pytest.mark.parametrize("duplicated", ["access_token_hash", "refresh_token_hash"])
def test_two_tokens_cannot_share_an_access_or_refresh_hash(session: Session, duplicated: str) -> None:
    user, client = _add_user(session), _add_client(session)
    first, second = _token(user, client, "1"), _token(user, client, "2")
    setattr(second, duplicated, getattr(first, duplicated))
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_user_can_approve_a_client_only_once(session: Session) -> None:
    user, client = _add_user(session), _add_client(session)
    session.add(OAuthConsent(user_id=user.id, client_id=client.client_id))
    session.flush()
    session.add(OAuthConsent(user_id=user.id, client_id=client.client_id))

    with pytest.raises(IntegrityError):
        session.flush()


def test_a_token_for_an_unregistered_client_is_rejected(session: Session) -> None:
    user = _add_user(session)
    session.add(_token(user, OAuthClient(client_id="never-registered", client_name="x", redirect_uris=[])))

    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_a_user_removes_their_tokens_and_consents(session: Session) -> None:
    user, client = _add_user(session), _add_client(session)
    session.add_all([_token(user, client), OAuthConsent(user_id=user.id, client_id=CLIENT_ID)])
    session.flush()

    session.delete(user)
    session.flush()

    assert [_count(session, model) for model in (OAuthToken, OAuthConsent)] == [0, 0]


def test_deleting_a_client_removes_only_its_own_tokens_and_consents(session: Session) -> None:
    user = _add_user(session)
    doomed, kept = _add_client(session), _add_client(session, OTHER_CLIENT_ID)
    session.add_all(
        [
            _token(user, doomed, "doomed"),
            _token(user, kept, "kept"),
            OAuthConsent(user_id=user.id, client_id=doomed.client_id),
            OAuthConsent(user_id=user.id, client_id=kept.client_id),
        ]
    )
    session.flush()

    session.delete(doomed)
    session.flush()

    assert [_count(session, model) for model in (OAuthToken, OAuthConsent)] == [1, 1]
