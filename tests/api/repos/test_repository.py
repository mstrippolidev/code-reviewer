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
from api.db.models.user_repo import UserRepo
from api.repos.errors import IndexedFileNotFoundError, RepoAlreadyRegisteredError, RepoNotFoundError
from api.repos.repository import RegisteredRepoRepository


class _NoRows:
    def all(self) -> list:
        return []


class RecordingSession:
    def __init__(self, scalar_result=None, flush_error: Exception | None = None) -> None:
        self._scalar_result = scalar_result
        self._flush_error = flush_error
        self.statements: list = []
        self.added: list[RegisteredRepo | UserRepo] = []
        self.events: list[str] = []
        self.refreshed: list[RegisteredRepo] = []
        self.deleted: list[RegisteredRepo] = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self._scalar_result

    async def scalars(self, statement):
        self.statements.append(statement)
        return _NoRows()

    async def execute(self, statement) -> None:
        self.statements.append(statement)

    def add(self, row: RegisteredRepo | UserRepo) -> None:
        self.added.append(row)
        self.events.append(type(row).__name__)

    async def commit(self) -> None:
        return None

    async def refresh(self, row: RegisteredRepo) -> None:
        self.refreshed.append(row)

    async def delete(self, row: RegisteredRepo) -> None:
        self.deleted.append(row)

    async def flush(self) -> None:
        self.events.append("flush")
        if self._flush_error:
            raise self._flush_error


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
    repository = RegisteredRepoRepository(RecordingSession(flush_error=violation))

    with pytest.raises(RepoAlreadyRegisteredError, match="already registered"):
        await repository.add(_make_registered_repo())


@pytest.mark.asyncio
async def test_add_links_the_owner_to_the_new_repo() -> None:
    """Verify that a newly registered repo shows up in its owner's list."""
    session = RecordingSession()
    registered = _make_registered_repo(repo_id=10, registered_by_user_id=7)

    await RegisteredRepoRepository(session).add(registered)

    link = session.added[-1]
    assert (link.user_id, link.repo_id) == (7, 10)


@pytest.mark.asyncio
async def test_add_saves_the_repo_before_its_link() -> None:
    """Verify that the repo row is flushed first, since the link's foreign key points at it."""
    session = RecordingSession()

    await RegisteredRepoRepository(session).add(_make_registered_repo())

    assert session.events == ["RegisteredRepo", "flush", "UserRepo"]


@pytest.mark.asyncio
async def test_add_does_not_link_anyone_when_the_registration_conflicts() -> None:
    """Verify that losing a registration race leaves no stray link behind."""
    violation = IntegrityError("INSERT INTO registered_repos", {}, Exception("duplicate key"))
    session = RecordingSession(flush_error=violation)

    with pytest.raises(RepoAlreadyRegisteredError):
        await RegisteredRepoRepository(session).add(_make_registered_repo())

    assert all(not isinstance(row, UserRepo) for row in session.added)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_link_id,expected", [(5, True), (None, False)])
async def test_is_linked_reflects_whether_a_link_row_exists(existing_link_id: int | None, expected: bool) -> None:
    """Verify that a user counts as linked exactly when a link row is found."""
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=existing_link_id))

    assert await repository.is_linked(7, 10) is expected


@pytest.mark.asyncio
async def test_add_link_adds_a_link_when_the_user_is_not_linked_yet() -> None:
    """Verify that linking a second user to an already registered repo stores their link."""
    session = RecordingSession(scalar_result=None)

    await RegisteredRepoRepository(session).add_link(7, 10)

    assert [(link.user_id, link.repo_id) for link in session.added] == [(7, 10)]


@pytest.mark.asyncio
async def test_add_link_does_nothing_when_the_user_is_already_linked() -> None:
    """Verify that registering the same repo twice is safe and never duplicates a link."""
    session = RecordingSession(scalar_result=5)

    await RegisteredRepoRepository(session).add_link(7, 10)

    assert session.added == []


@pytest.mark.asyncio
async def test_remove_link_targets_only_that_users_link_to_that_repo() -> None:
    """Verify that unlinking one user cannot remove another user's link or another repo's link."""
    session = RecordingSession()

    await RegisteredRepoRepository(session).remove_link(7, 10)

    assert sorted(session.statements[0].compile().params.values()) == [7, 10]


@pytest.mark.asyncio
async def test_list_registered_by_reads_through_the_link_table() -> None:
    """Verify that the list is built from the user's links, so a repo registered by someone else can appear."""
    session = RecordingSession()

    await RegisteredRepoRepository(session).list_registered_by(42)

    assert "user_repos" in str(session.statements[0])


@pytest.mark.asyncio
async def test_add_refreshes_the_row_so_server_defaults_are_loaded() -> None:
    """Verify that a committed row is refreshed before it is serialised back to the client."""
    session = RecordingSession()
    registered = _make_registered_repo()
    repository = RegisteredRepoRepository(session)

    await repository.add(registered)

    assert session.refreshed == [registered]


@pytest.mark.asyncio
@pytest.mark.parametrize("registered_id,expected", [(5, True), (None, False)])
async def test_is_registered_reflects_whether_a_repo_row_exists(registered_id: int | None, expected: bool) -> None:
    """Verify that a repo counts as registered exactly when its row is found, whatever its status."""
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=registered_id))

    assert await repository.is_registered(10) is expected


@pytest.mark.asyncio
async def test_find_by_repo_id_returns_the_registered_repo() -> None:
    """Verify that the stored row is returned as is."""
    existing = _make_registered_repo()
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=existing))

    assert await repository.find_by_repo_id(10) is existing


@pytest.mark.asyncio
async def test_find_by_repo_id_raises_when_the_repo_is_not_registered() -> None:
    """Verify that a missing repo is an error, never a None the caller might forget to check."""
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=None))

    with pytest.raises(RepoNotFoundError):
        await repository.find_by_repo_id(10)


@pytest.mark.asyncio
async def test_find_indexed_content_raises_when_the_file_has_no_stored_source() -> None:
    """Verify that an indexed row with content=None is treated as missing.

    Rows indexed before content was stored have no source to show a reviewer.
    """
    legacy_row = _make_indexed_file(content=None)
    repository = RegisteredRepoRepository(RecordingSession(scalar_result=legacy_row))

    with pytest.raises(IndexedFileNotFoundError, match="src/module.py"):
        await repository.find_indexed_content(10, "src/module.py")


@pytest.mark.asyncio
async def test_list_registered_by_filters_on_the_registering_user() -> None:
    """Verify that the list query is scoped to the caller's id, so no other user's repo can come back."""
    session = RecordingSession()

    await RegisteredRepoRepository(session).list_registered_by(42)

    assert 42 in session.statements[0].compile().params.values()


@pytest.mark.asyncio
async def test_list_registered_by_compares_the_id_with_the_links_user_column() -> None:
    """Verify that the id is compared with the link's user, not with the repo's own id."""
    session = RecordingSession()

    await RegisteredRepoRepository(session).list_registered_by(42)

    assert "user_repos.user_id" in str(session.statements[0])
