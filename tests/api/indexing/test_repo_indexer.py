"""
    Tests for RepoIndexer against fakes: no real DB, no real GitHub calls, no real
    embedding model. Tarballs are built in-memory to exercise the real extraction,
    path-safety, and walk logic rather than faking those away too.
"""
import os
import tarfile
from io import BytesIO

import pytest

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.indexing.repo_indexer import (
    RepoIndexer,
    RepoIndexerDependencies,
    RepoIndexUserNotFoundError,
    RepoTarballLayoutError,
    _find_extracted_repo_root,
    _is_safe_tar_member,
    _walk_repo_files,
)
from api.schemas.indexing import RepoRegisteredMessage
from code_reviewer.rag.repo_data import RepoData

TOP_LEVEL_DIR = "octocat-hello-world-abc123"


def _make_tarball(files: dict[str, bytes] | None = None, *, top_level_dir: str = TOP_LEVEL_DIR) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name=top_level_dir)
        info.type = tarfile.DIRTYPE
        archive.addfile(info)
        for relative_path, content in (files or {}).items():
            file_info = tarfile.TarInfo(name=f"{top_level_dir}/{relative_path}")
            file_info.size = len(content)
            archive.addfile(file_info, BytesIO(content))
    return buffer.getvalue()


def _make_tarball_with_raw_members(members: list[tuple[str, bytes | None]]) -> bytes:
    """content=None marks a directory entry; otherwise a regular file with that content."""
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in members:
            if content is None:
                info = tarfile.TarInfo(name=name)
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                archive.addfile(info, BytesIO(content))
    return buffer.getvalue()


class FakeAsyncSession:
    """Blind to query shape, like the repos router's fake session: seeded per test."""

    def __init__(self, *, users: dict[int, User] | None = None, registered_repo: RegisteredRepo | None = None) -> None:
        self.users = users or {}
        self.registered_repo = registered_repo
        self.added: list[object] = []
        self.commit_count = 0

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def get(self, model, primary_key: int) -> object | None:
        if model is User:
            return self.users.get(primary_key)
        return None

    async def scalar(self, _statement) -> RegisteredRepo | None:
        return self.registered_repo

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1

    @property
    def indexed_files(self) -> list[IndexedFile]:
        return [row for row in self.added if isinstance(row, IndexedFile)]

    def indexed_file(self, file_path: str) -> IndexedFile:
        [match] = [row for row in self.indexed_files if row.file_path == file_path]
        return match


class FakeDatabaseEngine:
    def __init__(self, session: FakeAsyncSession) -> None:
        self._session = session

    def new_session(self) -> FakeAsyncSession:
        return self._session


class FakeGitHubClient:
    def __init__(
        self,
        *,
        commit_sha: str = "abc123",
        tarball: bytes = b"",
        commit_error: Exception | None = None,
        tarball_error: Exception | None = None,
    ) -> None:
        self._commit_sha = commit_sha
        self._tarball = tarball
        self._commit_error = commit_error
        self._tarball_error = tarball_error

    async def fetch_branch_commit_sha(self, _access_token: str, _full_name: str, _ref: str) -> str:
        if self._commit_error:
            raise self._commit_error
        return self._commit_sha

    async def download_tarball(self, _access_token: str, _full_name: str, _ref: str) -> bytes:
        if self._tarball_error:
            raise self._tarball_error
        return self._tarball


class FakeTokenCipher:
    def __init__(self, *, decrypt_error: Exception | None = None) -> None:
        self._decrypt_error = decrypt_error

    def decrypt(self, _ciphertext: str) -> str:
        if self._decrypt_error:
            raise self._decrypt_error
        return "gho_token"


class FakeRagManager:
    def __init__(self, *, fail_paths: frozenset[str] = frozenset()) -> None:
        self._fail_paths = fail_paths
        self.indexed: list[tuple[RepoData, str, str]] = []

    def index_file(self, repo_data: RepoData, file_path: str, content: str) -> None:
        if file_path in self._fail_paths:
            raise RuntimeError(f"embedding failed for {file_path}")
        self.indexed.append((repo_data, file_path, content))


def _make_user(user_id: int = 1) -> User:
    return User(
        id=user_id,
        github_id=user_id,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token="encrypted",
        github_granted_scopes="repo",
    )


def _make_repo_msg(**overrides) -> RepoRegisteredMessage:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "registered_by_user_id": 1,
    }
    defaults.update(overrides)
    return RepoRegisteredMessage(**defaults)


def _make_indexer(
    *,
    session: FakeAsyncSession,
    github_client: FakeGitHubClient | None = None,
    token_cipher: FakeTokenCipher | None = None,
    rag_manager: FakeRagManager | None = None,
) -> tuple[RepoIndexer, FakeRagManager]:
    rag = rag_manager or FakeRagManager()
    dependencies = RepoIndexerDependencies(
        database_engine=FakeDatabaseEngine(session),
        http_client=None,
        token_cipher=token_cipher or FakeTokenCipher(),
        github_client=github_client or FakeGitHubClient(),
        rag_manager=rag,
    )
    return RepoIndexer(dependencies), rag


@pytest.mark.asyncio
async def test_index_repo_indexes_python_files_and_skips_non_python_files() -> None:
    tarball = _make_tarball({"main.py": b"print('hi')", "helper.py": b"x = 1", "README.md": b"# hi"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert {path for _, path, _ in rag.indexed} == {"main.py", "helper.py"}
    assert session.indexed_file("main.py").status == IndexedFileStatus.INDEXED
    assert session.indexed_file("helper.py").status == IndexedFileStatus.INDEXED
    readme = session.indexed_file("README.md")
    assert readme.status == IndexedFileStatus.SKIPPED
    assert readme.status_reason == "not Python"
    assert session.registered_repo.status == RepoIndexStatus.INDEXED


@pytest.mark.asyncio
async def test_index_repo_prunes_excluded_directories_entirely() -> None:
    tarball = _make_tarball(
        {
            "main.py": b"print('hi')",
            ".venv/lib/site.py": b"junk",
            "__pycache__/main.cpython-314.pyc": b"junk",
            ".git/HEAD": b"ref: refs/heads/main",
            "node_modules/pkg/index.js": b"junk",
        }
    )
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    recorded_paths = {row.file_path for row in session.indexed_files}
    assert recorded_paths == {"main.py"}
    assert {path for _, path, _ in rag.indexed} == {"main.py"}


@pytest.mark.asyncio
async def test_index_repo_marks_a_single_failing_file_as_failed_without_failing_the_repo() -> None:
    tarball = _make_tarball({"good.py": b"x = 1", "bad.py": b"y = 2", "also_good.py": b"z = 3"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    rag = FakeRagManager(fail_paths=frozenset({"bad.py"}))
    indexer, _ = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball), rag_manager=rag)

    await indexer.index_repo(_make_repo_msg())

    assert session.indexed_file("good.py").status == IndexedFileStatus.INDEXED
    assert session.indexed_file("also_good.py").status == IndexedFileStatus.INDEXED
    bad = session.indexed_file("bad.py")
    assert bad.status == IndexedFileStatus.FAILED
    assert "embedding failed" in bad.status_reason
    assert session.registered_repo.status == RepoIndexStatus.INDEXED


@pytest.mark.asyncio
async def test_index_repo_marks_a_binary_or_undecodable_file_as_failed() -> None:
    tarball = _make_tarball({"good.py": b"x = 1", "broken.py": b"\xff\xfe\x00bad-utf8"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert session.indexed_file("good.py").status == IndexedFileStatus.INDEXED
    broken = session.indexed_file("broken.py")
    assert broken.status == IndexedFileStatus.FAILED
    assert broken.status_reason
    assert {path for _, path, _ in rag.indexed} == {"good.py"}
    assert session.registered_repo.status == RepoIndexStatus.INDEXED


@pytest.mark.asyncio
async def test_index_repo_handles_an_empty_repo() -> None:
    tarball = _make_tarball({})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert session.indexed_files == []
    assert rag.indexed == []
    assert session.registered_repo.status == RepoIndexStatus.INDEXED


@pytest.mark.asyncio
async def test_index_repo_filters_out_path_traversal_members() -> None:
    tarball = _make_tarball_with_raw_members(
        [
            (TOP_LEVEL_DIR, None),
            (f"{TOP_LEVEL_DIR}/safe.py", b"x = 1"),
            ("../evil.py", b"malicious"),
            (f"{TOP_LEVEL_DIR}/../../also_evil.py", b"malicious"),
        ]
    )
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    recorded_paths = {row.file_path for row in session.indexed_files}
    assert recorded_paths == {"safe.py"}
    assert {path for _, path, _ in rag.indexed} == {"safe.py"}
    assert session.registered_repo.status == RepoIndexStatus.INDEXED


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_on_unexpected_tarball_layout() -> None:
    tarball = _make_tarball_with_raw_members(
        [("first-dir", None), ("second-dir", None), ("first-dir/a.py", b"x = 1")]
    )
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, _ = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    with pytest.raises(RepoTarballLayoutError):
        await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED
    assert session.registered_repo.status_reason


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_when_user_not_found() -> None:
    session = FakeAsyncSession(users={}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, _ = _make_indexer(session=session)

    with pytest.raises(RepoIndexUserNotFoundError):
        await indexer.index_repo(_make_repo_msg(registered_by_user_id=404))

    assert session.registered_repo.status == RepoIndexStatus.FAILED


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_when_token_decryption_fails() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, _ = _make_indexer(session=session, token_cipher=FakeTokenCipher(decrypt_error=ValueError("bad key")))

    with pytest.raises(ValueError):
        await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_when_commit_sha_fetch_fails() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(commit_error=RuntimeError("github unreachable"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED
    assert "github unreachable" in session.registered_repo.status_reason


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_when_tarball_download_fails() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(tarball_error=RuntimeError("download timed out"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED


@pytest.mark.asyncio
async def test_index_repo_does_not_raise_when_the_registered_repo_row_is_missing() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=None)
    github_client = FakeGitHubClient(commit_error=RuntimeError("boom"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())


@pytest.mark.asyncio
async def test_index_repo_passes_correctly_typed_repo_data_to_index_file() -> None:
    tarball = _make_tarball({"main.py": b"print(1)"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, rag = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball, commit_sha="deadbeef"))

    await indexer.index_repo(_make_repo_msg(repo_id=10, owner_id=99))

    [(repo_data, file_path, content)] = rag.indexed
    assert repo_data == RepoData(repo_id="10", commit_sha="deadbeef", owner_id="99")
    assert file_path == "main.py"
    assert content == "print(1)"


def test_is_safe_tar_member_rejects_path_traversal(tmp_path) -> None:
    extract_dir = str(tmp_path)
    traversal_member = tarfile.TarInfo(name="../../etc/passwd")

    assert _is_safe_tar_member(traversal_member, extract_dir) is False


def test_is_safe_tar_member_accepts_a_normal_path(tmp_path) -> None:
    extract_dir = str(tmp_path)
    normal_member = tarfile.TarInfo(name="repo-abc123/src/main.py")

    assert _is_safe_tar_member(normal_member, extract_dir) is True


def test_find_extracted_repo_root_raises_when_no_entries(tmp_path) -> None:
    with pytest.raises(RepoTarballLayoutError):
        _find_extracted_repo_root(str(tmp_path))


def test_find_extracted_repo_root_raises_when_multiple_entries(tmp_path) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()

    with pytest.raises(RepoTarballLayoutError):
        _find_extracted_repo_root(str(tmp_path))


def test_walk_repo_files_prunes_hidden_directories(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x = 1")
    (tmp_path / ".mypy_cache").mkdir()
    (tmp_path / ".mypy_cache" / "cache.json").write_text("{}")

    relative_paths = _walk_repo_files(str(tmp_path))

    assert relative_paths == [os.path.join("src", "main.py")]
