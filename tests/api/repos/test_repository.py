"""
    Tests for RegisteredRepoRepository against a recording fake session: no real DB.

    A fake cannot evaluate SQL, so the by-name lookup is checked through the statement it
    emits; the route-level behaviour is covered in tests/api/routers/test_repos_by_name.py.
"""
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.repos.errors import IndexedFileNotFoundError, RepoAlreadyRegisteredError, RepoNotFoundError
from api.repos.repository import RegisteredRepoRepository


class RecordingSession:
    def __init__(self, scalar_result=None, commit_error: Exception | None = None) -> None:
        self._scalar_result = scalar_result
        self._commit_error = commit_error
        self.statements: list = []
        self.added: list[RegisteredRepo] = []
        self.refreshed: list[RegisteredRepo] = []
        self.deleted: list[RegisteredRepo] = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self._scalar_result

    def add(self, row: RegisteredRepo) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        if self._commit_error:
            raise self._commit_error

    async def refresh(self, row: RegisteredRepo) -> None:
        self.refreshed.append(row)

    async def delete(self, row: RegisteredRepo) -> None:
        self.deleted.append(row)

    async def flush(self) -> None:
        return None


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "branch": "main",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.COMPLETED,
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return RegisteredRepo(**defaults)


def _make_indexed_file(**overrides) -> IndexedFile:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "file_path": "src/module.py",
        "status": IndexedFileStatus.INDEXED,
        "content": "def add(a, b):\n    return a + b\n",
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return IndexedFile(**defaults)


@pytest.mark.asyncio
async def test_find_by_full_name_compares_with_equality_not_pattern_matching() -> None:
    """Verify that the lookup never emits LIKE/ILIKE.

    Pattern matching would treat `_` and `%` in a repo name as wildcards and could return
    a different repo than the one asked for.
    """
    session = RecordingSession(scalar_result=_make_registered_repo())
    repository = RegisteredRepoRepository(session)

    await repository.find_by_full_name("octocat/hello_world")

    assert "LIKE" not in str(session.statements[0].compile()).upper()


@pytest.mark.asyncio
async def test_find_by_full_name_binds_the_lowercased_name_unchanged() -> None:
    """Verify that the requested name is lowercased and otherwise passed through verbatim.

    Wildcard characters must reach the database as literal text.
    """
    session = RecordingSession(scalar_result=_make_registered_repo())
    repository = RegisteredRepoRepository(session)

    await repository.find_by_full_name("OctoCat/Hello_World%")

    assert list(session.statements[0].compile().params.values()) == ["octocat/hello_world%"]


@pytest.mark.asyncio
async def test_find_by_full_name_returns_the_row_the_database_found() -> None:
    """Verify that the matched row is handed back to the caller untouched."""
    found = _make_registered_repo()
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=found))

    repo = await repository.find_by_full_name("octocat/hello-world")

    assert repo is found


@pytest.mark.asyncio
async def test_find_by_full_name_raises_when_no_repo_matches() -> None:
    """Verify that a missing repo raises instead of returning None."""
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=None))

    with pytest.raises(RepoNotFoundError, match="Could not find the repo"):
        await repository.find_by_full_name("nobody/nothing")


@pytest.mark.asyncio
async def test_add_translates_a_unique_violation_into_already_registered() -> None:
    """Verify that losing a registration race surfaces as a conflict, not a database error.

    Two requests can both pass the pre-check; the unique constraint settles the winner.
    """
    violation = IntegrityError("INSERT INTO registered_repos", {}, Exception("duplicate key"))
    repository = RegisteredRepoRepository(RecordingSession(commit_error=violation))

    with pytest.raises(RepoAlreadyRegisteredError, match="already registered"):
        await repository.add(_make_registered_repo())


@pytest.mark.asyncio
async def test_add_refreshes_the_row_so_server_defaults_are_loaded() -> None:
    """Verify that a committed row is refreshed before it is serialised back to the client."""
    session = RecordingSession()
    registered = _make_registered_repo()
    repository = RegisteredRepoRepository(session)

    await repository.add(registered)

    assert session.refreshed == [registered]


@pytest.mark.asyncio
async def test_reject_active_registration_allows_a_repo_never_registered() -> None:
    """Verify that a first-time registration deletes nothing."""
    session = RecordingSession(scalar_result=None)
    repository = RegisteredRepoRepository(session)

    await repository.reject_active_registration(10)

    assert session.deleted == []


@pytest.mark.asyncio
async def test_reject_active_registration_removes_a_failed_registration() -> None:
    """Verify that a failed registration is cleared so the repo can be registered again."""
    failed = _make_registered_repo(status=RepoIndexStatus.FAILED)
    session = RecordingSession(scalar_result=failed)
    repository = RegisteredRepoRepository(session)

    await repository.reject_active_registration(10)

    assert session.deleted == [failed]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "active_status",
    [RepoIndexStatus.PENDING, RepoIndexStatus.INDEXING, RepoIndexStatus.PAUSED, RepoIndexStatus.COMPLETED],
)
async def test_reject_active_registration_refuses_every_non_failed_status(active_status: RepoIndexStatus) -> None:
    """Verify that only a FAILED registration may be replaced; any live one is a conflict."""
    existing = _make_registered_repo(status=active_status)
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=existing))

    with pytest.raises(RepoAlreadyRegisteredError):
        await repository.reject_active_registration(10)


@pytest.mark.asyncio
async def test_find_indexed_content_raises_when_the_file_has_no_stored_source() -> None:
    """Verify that an indexed row with content=None is treated as missing.

    Rows indexed before content was stored have no source to show a reviewer.
    """
    legacy_row = _make_indexed_file(content=None)
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=legacy_row))

    with pytest.raises(IndexedFileNotFoundError, match="src/module.py"):
        await repository.find_indexed_content(10, "src/module.py")
