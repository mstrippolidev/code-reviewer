"""
    Tests for GET /api/repos/name against fakes: no real DB, no real GitHub calls.

    The fake session answers the by-name lookup in Python, so these tests cover the route's
    behaviour; the SQL the repository emits is covered in tests/api/repos/test_repository.py.
"""
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.exception_handlers import register_repo_exception_handlers
from api.routers.repos import router as repos_router

REGISTERED_NAME = "octocat/hello-world"


class _ScalarsResult:
    def __init__(self, rows: list[IndexedFile]) -> None:
        self._rows = rows

    def all(self) -> list[IndexedFile]:
        return self._rows


class FakeAsyncSession:
    """Answers `scalar` as the by-name lookup and `scalars` as the per-repo file listing."""

    def __init__(self, repos: list[RegisteredRepo], indexed_files: list[IndexedFile]) -> None:
        self._repos = repos
        self._indexed_files = indexed_files

    async def scalar(self, statement) -> RegisteredRepo | None:
        requested_name = next(iter(statement.compile().params.values()))
        return next((repo for repo in self._repos if repo.full_name.lower() == requested_name), None)

    async def scalars(self, statement) -> _ScalarsResult:
        requested_repo_id = next(iter(statement.compile().params.values()))
        return _ScalarsResult([file for file in self._indexed_files if file.repo_id == requested_repo_id])


def _make_user() -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token="unused",
        github_granted_scopes="repo",
    )


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": REGISTERED_NAME,
        "default_branch": "main",
        "branch": "main",
        "commit_sha": "abc123",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.COMPLETED,
        "total_files_expected": 3,
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
        "status_reason": None,
        "indexed_at": datetime(2026, 1, 2),
        "created_at": datetime(2026, 1, 1),
    }
    defaults.update(overrides)
    return IndexedFile(**defaults)


def _build_app(repos: list[RegisteredRepo], indexed_files: list[IndexedFile]) -> FastAPI:
    app = FastAPI()
    app.include_router(repos_router)
    register_repo_exception_handlers(app)

    async def _fake_db_session():
        yield FakeAsyncSession(repos, indexed_files)

    app.dependency_overrides[get_db_session] = _fake_db_session
    return app


def _build_client(
    repos: list[RegisteredRepo] | None = None, indexed_files: list[IndexedFile] | None = None
) -> TestClient:
    app = _build_app(repos or [], indexed_files or [])
    app.dependency_overrides[get_current_user] = _make_user
    return TestClient(app)


def test_get_repo_by_name_returns_the_matching_repo() -> None:
    """Verify that a registered repo is found by its exact full name."""
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME})

    assert response.json()["repo"]["repo_id"] == 10


def test_get_repo_by_name_matches_regardless_of_letter_case() -> None:
    """Verify that GitHub's case-insensitive names resolve to the same repo.

    The MCP client passes whatever casing the user typed.
    """
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name", params={"full_name": "OctoCat/Hello-World"})

    assert response.json()["repo"]["repo_id"] == 10


def test_get_repo_by_name_selects_the_requested_repo_among_several() -> None:
    """Verify that the lookup is keyed by name, not by returning the first registered repo."""
    other = _make_registered_repo(id=1, repo_id=10, full_name="octocat/other")
    wanted = _make_registered_repo(id=2, repo_id=20, full_name=REGISTERED_NAME)
    client = _build_client(repos=[other, wanted])

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME})

    assert response.json()["repo"]["repo_id"] == 20


def test_get_repo_by_name_returns_404_for_an_unregistered_name() -> None:
    """Verify that an unknown repo is reported as missing rather than as a server error."""
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name", params={"full_name": "nobody/nothing"})

    assert response.status_code == 404


def test_get_repo_by_name_404_explains_that_the_repo_was_not_found() -> None:
    """Verify that the 404 carries a message the MCP client can relay to the calling LLM."""
    client = _build_client()

    response = client.get("/api/repos/name", params={"full_name": "nobody/nothing"})

    assert response.json() == {"detail": "Could not find the repo"}


def test_get_repo_by_name_returns_the_fields_the_mcp_status_tool_reads() -> None:
    """Verify the contract mcp_server depends on: status, branch, commit and expected file count."""
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME})

    repo = response.json()["repo"]
    assert {
        "status": repo["status"],
        "branch": repo["branch"],
        "commit_sha": repo["commit_sha"],
        "total_files_expected": repo["total_files_expected"],
    } == {"status": "completed", "branch": "main", "commit_sha": "abc123", "total_files_expected": 3}


def test_get_repo_by_name_omits_files_unless_requested() -> None:
    """Verify that files are not loaded by default, keeping the common lookup a single cheap query."""
    client = _build_client(repos=[_make_registered_repo()], indexed_files=[_make_indexed_file()])

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME})

    assert response.json()["files"] == []


def test_get_repo_by_name_with_files_lists_the_indexed_files() -> None:
    """Verify that with_files=true returns every file tracked for the repo."""
    files = [_make_indexed_file(id=1, file_path="src/a.py"), _make_indexed_file(id=2, file_path="src/b.py")]
    client = _build_client(repos=[_make_registered_repo()], indexed_files=files)

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME, "with_files": True})

    assert {file["file_path"] for file in response.json()["files"]} == {"src/a.py", "src/b.py"}


def test_get_repo_by_name_with_files_reports_each_files_status() -> None:
    """Verify that failed files stay distinguishable from indexed ones.

    The MCP status tool derives its failed count from these values.
    """
    files = [
        _make_indexed_file(id=1, file_path="src/a.py", status=IndexedFileStatus.INDEXED),
        _make_indexed_file(id=2, file_path="src/b.py", status=IndexedFileStatus.FAILED, status_reason="parse error"),
    ]
    client = _build_client(repos=[_make_registered_repo()], indexed_files=files)

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME, "with_files": True})

    assert {file["file_path"]: file["status"] for file in response.json()["files"]} == {
        "src/a.py": "indexed",
        "src/b.py": "failed",
    }


def test_get_repo_by_name_with_files_excludes_other_repos_files() -> None:
    """Verify that files are filtered by GitHub's repo_id, not by the table's primary key.

    The second file's repo_id equals the registered repo's primary key (1), so a lookup
    keyed on the wrong column would leak it into the response.
    """
    files = [
        _make_indexed_file(id=1, repo_id=10, file_path="mine.py"),
        _make_indexed_file(id=2, repo_id=1, file_path="matches-the-primary-key.py"),
        _make_indexed_file(id=3, repo_id=20, file_path="someone-elses.py"),
    ]
    client = _build_client(repos=[_make_registered_repo(id=1, repo_id=10)], indexed_files=files)

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME, "with_files": True})

    assert [file["file_path"] for file in response.json()["files"]] == ["mine.py"]


def test_get_repo_by_name_with_files_returns_an_empty_list_when_nothing_is_indexed() -> None:
    """Verify that a registered repo with no files yet is a valid, empty result rather than an error."""
    client = _build_client(repos=[_make_registered_repo(status=RepoIndexStatus.PENDING)])

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME, "with_files": True})

    assert response.json()["files"] == []


def test_get_repo_by_name_rejects_an_empty_full_name() -> None:
    """Verify that an empty name is refused before it reaches the database."""
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name", params={"full_name": ""})

    assert response.status_code == 422


def test_get_repo_by_name_requires_a_full_name() -> None:
    """Verify that omitting the name entirely is a validation error, not a lookup of everything."""
    client = _build_client(repos=[_make_registered_repo()])

    response = client.get("/api/repos/name")

    assert response.status_code == 422


def test_get_repo_by_name_requires_authentication() -> None:
    """Verify that the lookup is closed to callers without credentials.

    Registered repos are private to logged-in users; the MCP client always sends a token.
    """
    client = TestClient(_build_app(repos=[_make_registered_repo()], indexed_files=[]))

    response = client.get("/api/repos/name", params={"full_name": REGISTERED_NAME})

    assert response.status_code == 401
