"""
    Tests that the vector store connects with the real password: no database, PGVectorStore is faked.
"""
from types import SimpleNamespace

import pytest

from code_reviewer.rag import vector_store

REAL_PASSWORD = "s3cret-pw"


class FakeEmbedding:
    embed_dim = 8


@pytest.fixture
def password_protected_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_settings = SimpleNamespace(
        pg_user="code_reviewer_app",
        pg_password=REAL_PASSWORD,
        pg_host="code-reviewer-postgres-rw",
        pg_port=5432,
        pg_database="code-reviewer",
    )
    monkeypatch.setattr(vector_store, "settings", fake_settings)


@pytest.fixture
def captured_from_params_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    def fake_from_params(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(vector_store.PGVectorStore, "from_params", staticmethod(fake_from_params))
    return captured


def test_build_connection_string_keeps_the_real_password(password_protected_settings: None) -> None:
    """Verify the rendered URL carries the password, not SQLAlchemy's '***' mask."""
    connection_string = vector_store.build_connection_string("postgresql+psycopg2")

    assert f":{REAL_PASSWORD}@" in connection_string


def test_vector_store_receives_the_real_password_for_sync_connections(
    password_protected_settings: None, captured_from_params_kwargs: dict
) -> None:
    """Verify PGVectorStore, which str()s whatever URL it gets, is handed an unmasked sync URL.

    A masked URL only fails against a Postgres that checks passwords, which a trust-auth dev database never does.
    """
    vector_store.create_vector_store_instance(embedding=FakeEmbedding())

    assert REAL_PASSWORD in captured_from_params_kwargs["connection_string"]


def test_vector_store_receives_the_real_password_for_async_connections(
    password_protected_settings: None, captured_from_params_kwargs: dict
) -> None:
    """Verify the async URL is unmasked too."""
    vector_store.create_vector_store_instance(embedding=FakeEmbedding())

    assert REAL_PASSWORD in captured_from_params_kwargs["async_connection_string"]
