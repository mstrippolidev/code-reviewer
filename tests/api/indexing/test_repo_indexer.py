"""
    Tests for RepoIndexer against fakes: no real DB, no real GitHub calls, no real Kafka broker.
    Tarballs are built in-memory to exercise the real extraction, path-safety, and walk logic
    rather than faking those away too. Embedding itself is out of scope here — RepoIndexer only
    walks a repo and dispatches eligible files to repo.file.index; RepoFileIndexConsumer (tested
    in test_repo_file_index_consumer.py) is what actually embeds them.
"""
import os
import tarfile
from collections.abc import Callable
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
    _MAX_INLINE_FILE_BYTES,
)
from api.indexing.topics import REPO_FILE_INDEX, REPO_FILE_PROGRESS, REPO_STATUS_PROGRESS
from api.schemas.indexing import RepoFileIndexMessage, RepoRegisteredMessage
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage

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
        self.rollback_count = 0

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def get(self, model, primary_key: int) -> object | None:
        if model is User:
            return self.users.get(primary_key)
        return None

    async def scalar(self, statement) -> object | None:
        entity = statement.column_descriptions[0]["entity"]
        if entity is IndexedFile:
            params = list(statement.compile().params.values())
            return next((row for row in self.indexed_files if row.file_path in params), None)
        return self.registered_repo

    async def scalars(self, statement) -> "_FakeScalarResult":
        entity = statement.column_descriptions[0]["entity"]
        if entity is IndexedFile:
            return _FakeScalarResult(
                [row.file_path for row in self.indexed_files if row.status == IndexedFileStatus.FAILED]
            )
        return _FakeScalarResult([])

    def add(self, row: object) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    @property
    def indexed_files(self) -> list[IndexedFile]:
        return [row for row in self.added if isinstance(row, IndexedFile)]

    def indexed_file(self, file_path: str) -> IndexedFile:
        [match] = [row for row in self.indexed_files if row.file_path == file_path]
        return match


class _FakeScalarResult:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


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


class FakeRepoProducer:
    """Records every publish() call; RepoIndexer never publishes to a DLQ, so that's not faked here."""

    def __init__(
        self,
        *,
        publish_error: Exception | None = None,
        on_publish: Callable[[str, object], None] | None = None,
    ) -> None:
        self._publish_error = publish_error
        self._on_publish = on_publish
        self.published: list[tuple[str, object, bytes]] = []

    async def publish(self, topic: str, message: object, key: bytes) -> None:
        if self._publish_error:
            raise self._publish_error
        self.published.append((topic, message, key))
        if self._on_publish:
            self._on_publish(topic, message)

    @property
    def file_index_messages(self) -> list[RepoFileIndexMessage]:
        return [message for topic, message, _ in self.published if topic == REPO_FILE_INDEX]

    @property
    def progress_messages(self) -> list[RepoFileProgressMessage]:
        return [message for topic, message, _ in self.published if topic == REPO_FILE_PROGRESS]

    @property
    def status_messages(self) -> list[RepoStatusProgressMessage]:
        return [message for topic, message, _ in self.published if topic == REPO_STATUS_PROGRESS]


class FakeCompletionFinalizer:
    """Mirrors just enough of RepoCompletionFinalizer's contract for RepoIndexer's own tests;
    RepoCompletionFinalizer's real SQL-driven behavior has its own test file."""

    def __init__(self) -> None:
        self.finalize_calls: list[int] = []

    async def finalize_if_complete(self, repo_id: int, session: FakeAsyncSession) -> None:
        self.finalize_calls.append(repo_id)
        repo = session.registered_repo
        if repo is None or repo.total_files_expected is None:
            return
        terminal_statuses = {IndexedFileStatus.INDEXED, IndexedFileStatus.SKIPPED, IndexedFileStatus.FAILED}
        terminal_count = len([row for row in session.indexed_files if row.status in terminal_statuses])
        if terminal_count >= repo.total_files_expected:
            repo.status = RepoIndexStatus.COMPLETED


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
    repo_producer: FakeRepoProducer | None = None,
    completion_finalizer: FakeCompletionFinalizer | None = None,
    max_concurrent_file_dispatch: int = 8,
) -> tuple[RepoIndexer, FakeRepoProducer]:
    producer = repo_producer or FakeRepoProducer()
    dependencies = RepoIndexerDependencies(
        database_engine=FakeDatabaseEngine(session),
        http_client=None,
        token_cipher=token_cipher or FakeTokenCipher(),
        github_client=github_client or FakeGitHubClient(),
        repo_producer=producer,
        completion_finalizer=completion_finalizer or FakeCompletionFinalizer(),
        max_concurrent_file_dispatch=max_concurrent_file_dispatch,
    )
    return RepoIndexer(dependencies), producer


@pytest.mark.asyncio
async def test_index_repo_queues_python_files_and_skips_non_python_files() -> None:
    tarball = _make_tarball({"main.py": b"print('hi')", "helper.py": b"x = 1", "README.md": b"# hi"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert {message.file_path for message in producer.file_index_messages} == {"main.py", "helper.py"}
    assert session.indexed_file("main.py").status == IndexedFileStatus.PENDING
    assert session.indexed_file("helper.py").status == IndexedFileStatus.PENDING
    readme = session.indexed_file("README.md")
    assert readme.status == IndexedFileStatus.SKIPPED
    assert readme.status_reason == "not Python"
    [readme_progress] = [message for message in producer.progress_messages if message.file_path == "README.md"]
    assert readme_progress.status == IndexedFileStatus.SKIPPED
    # main.py and helper.py are only PENDING at this point — the repo can't be INDEXED
    # until RepoFileIndexConsumer actually embeds them and calls the completion finalizer.
    assert session.registered_repo.status == RepoIndexStatus.INDEXING


@pytest.mark.asyncio
async def test_index_repo_sets_total_files_expected_including_skipped_files() -> None:
    tarball = _make_tarball({"main.py": b"print('hi')", "helper.py": b"x = 1", "README.md": b"# hi"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, _ = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.total_files_expected == 3


@pytest.mark.asyncio
async def test_index_repo_publishes_a_repo_file_index_message_with_correct_content() -> None:
    tarball = _make_tarball({"main.py": b"print(1)"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball, commit_sha="deadbeef"))

    await indexer.index_repo(_make_repo_msg(repo_id=10, owner_id=99))

    [message] = producer.file_index_messages
    assert message == RepoFileIndexMessage(
        repo_id=10, owner_id=99, commit_sha="deadbeef", file_path="main.py", content="print(1)"
    )
    [(_topic, _message, key)] = [entry for entry in producer.published if entry[0] == REPO_FILE_INDEX]
    assert key == b"10:main.py"


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
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    recorded_paths = {row.file_path for row in session.indexed_files}
    assert recorded_paths == {"main.py"}
    assert {message.file_path for message in producer.file_index_messages} == {"main.py"}


@pytest.mark.asyncio
async def test_index_repo_marks_a_binary_or_undecodable_file_as_failed() -> None:
    tarball = _make_tarball({"good.py": b"x = 1", "broken.py": b"\xff\xfe\x00bad-utf8"})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert session.indexed_file("good.py").status == IndexedFileStatus.PENDING
    broken = session.indexed_file("broken.py")
    assert broken.status == IndexedFileStatus.FAILED
    assert broken.status_reason
    assert {message.file_path for message in producer.file_index_messages} == {"good.py"}


@pytest.mark.asyncio
async def test_index_repo_skips_a_file_that_exceeds_the_inline_size_cap() -> None:
    oversized_content = b"x" * (_MAX_INLINE_FILE_BYTES + 1)
    tarball = _make_tarball({"good.py": b"x = 1", "huge.py": oversized_content})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    huge = session.indexed_file("huge.py")
    assert huge.status == IndexedFileStatus.SKIPPED
    assert huge.status_reason == "too large to index inline"
    assert {message.file_path for message in producer.file_index_messages} == {"good.py"}


@pytest.mark.asyncio
async def test_index_repo_handles_an_empty_repo() -> None:
    tarball = _make_tarball({})
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert session.indexed_files == []
    assert producer.file_index_messages == []
    # No files at all means total_files_expected == 0, so the finalizer's own
    # terminal_count >= total_files_expected check is satisfied immediately.
    assert session.registered_repo.status == RepoIndexStatus.COMPLETED


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
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    recorded_paths = {row.file_path for row in session.indexed_files}
    assert recorded_paths == {"safe.py"}
    assert {message.file_path for message in producer.file_index_messages} == {"safe.py"}


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
async def test_index_repo_rolls_back_the_session_before_marking_the_repo_failed() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(commit_error=RuntimeError("github unreachable"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())

    assert session.rollback_count == 1
    assert session.registered_repo.status == RepoIndexStatus.FAILED


@pytest.mark.asyncio
async def test_index_repo_raises_and_marks_repo_failed_when_tarball_download_fails() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(tarball_error=RuntimeError("download timed out"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED


@pytest.mark.asyncio
async def test_mark_repo_failed_publishes_repo_status_progress() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(commit_error=RuntimeError("github unreachable"))
    indexer, producer = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.index_repo(_make_repo_msg())

    [message] = producer.status_messages
    assert message.repo_id == 10
    assert message.status == RepoIndexStatus.FAILED
    assert "github unreachable" in message.status_reason


@pytest.mark.asyncio
async def test_mark_repo_failed_swallows_a_status_progress_publish_failure() -> None:
    session = FakeAsyncSession(users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING))
    github_client = FakeGitHubClient(commit_error=RuntimeError("github unreachable"))
    producer = FakeRepoProducer(publish_error=RuntimeError("broker unreachable"))
    indexer, _ = _make_indexer(session=session, github_client=github_client, repo_producer=producer)

    with pytest.raises(RuntimeError, match="github unreachable"):
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
async def test_index_repo_skips_files_that_already_have_an_indexed_file_row() -> None:
    """Simulates a resumed walk: repo.registered is re-published after a pause, and a file
    already dispatched on the first pass must not be dispatched again."""
    tarball = _make_tarball({"already-done.py": b"x = 1", "new-file.py": b"y = 2"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PAUSED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="already-done.py", status=IndexedFileStatus.INDEXED))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.index_repo(_make_repo_msg())

    assert {message.file_path for message in producer.file_index_messages} == {"new-file.py"}
    assert len([row for row in session.indexed_files if row.file_path == "already-done.py"]) == 1
    assert session.registered_repo.total_files_expected == 2


@pytest.mark.asyncio
async def test_index_repo_stops_dispatching_once_the_repo_is_paused_mid_walk() -> None:
    tarball = _make_tarball({"first.py": b"a = 1", "second.py": b"b = 2", "third.py": b"c = 3"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.PENDING)
    )

    def pause_once_the_first_file_dispatches(topic: str, _message: object) -> None:
        if topic == REPO_FILE_INDEX:
            session.registered_repo.status = RepoIndexStatus.PAUSED

    producer = FakeRepoProducer(on_publish=pause_once_the_first_file_dispatches)
    indexer, _ = _make_indexer(
        session=session,
        github_client=FakeGitHubClient(tarball=tarball),
        repo_producer=producer,
        max_concurrent_file_dispatch=1,
    )

    await indexer.index_repo(_make_repo_msg())

    assert len(producer.file_index_messages) == 1
    assert session.registered_repo.total_files_expected == 3
    assert session.registered_repo.status == RepoIndexStatus.PAUSED


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


@pytest.mark.asyncio
async def test_retry_failed_files_redispatches_only_failed_files() -> None:
    tarball = _make_tarball({"good.py": b"x = 1", "broken.py": b"y = 2"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.COMPLETED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="good.py", status=IndexedFileStatus.INDEXED))
    session.added.append(
        IndexedFile(repo_id=10, file_path="broken.py", status=IndexedFileStatus.FAILED, status_reason="boom")
    )
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.retry_failed_files(_make_repo_msg())

    assert {message.file_path for message in producer.file_index_messages} == {"broken.py"}


@pytest.mark.asyncio
async def test_retry_failed_files_publishes_fresh_content_for_the_retried_file() -> None:
    tarball = _make_tarball({"broken.py": b"print('fixed now')"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.FAILED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="broken.py", status=IndexedFileStatus.FAILED))
    indexer, producer = _make_indexer(
        session=session, github_client=FakeGitHubClient(tarball=tarball, commit_sha="fixed-sha")
    )

    await indexer.retry_failed_files(_make_repo_msg(repo_id=10, owner_id=99))

    [message] = producer.file_index_messages
    assert message == RepoFileIndexMessage(
        repo_id=10, owner_id=99, commit_sha="fixed-sha", file_path="broken.py", content="print('fixed now')"
    )


@pytest.mark.asyncio
async def test_retry_failed_files_does_not_touch_an_already_indexed_file() -> None:
    tarball = _make_tarball({"good.py": b"x = 1"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.COMPLETED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="good.py", status=IndexedFileStatus.INDEXED))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.retry_failed_files(_make_repo_msg())

    assert producer.file_index_messages == []
    assert session.indexed_file("good.py").status == IndexedFileStatus.INDEXED


@pytest.mark.asyncio
async def test_retry_failed_files_marks_a_file_failed_again_when_it_no_longer_exists_in_the_tarball() -> None:
    tarball = _make_tarball({})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.FAILED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="removed.py", status=IndexedFileStatus.FAILED))
    indexer, producer = _make_indexer(session=session, github_client=FakeGitHubClient(tarball=tarball))

    await indexer.retry_failed_files(_make_repo_msg())

    removed = session.indexed_file("removed.py")
    assert removed.status == IndexedFileStatus.FAILED
    assert removed.status_reason
    assert producer.file_index_messages == []
    [progress] = [message for message in producer.progress_messages if message.file_path == "removed.py"]
    assert progress.status == IndexedFileStatus.FAILED


@pytest.mark.asyncio
async def test_retry_failed_files_calls_the_completion_finalizer_on_success() -> None:
    tarball = _make_tarball({"broken.py": b"y = 2"})
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.FAILED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="broken.py", status=IndexedFileStatus.FAILED))
    finalizer = FakeCompletionFinalizer()
    indexer, _ = _make_indexer(
        session=session, github_client=FakeGitHubClient(tarball=tarball), completion_finalizer=finalizer
    )

    await indexer.retry_failed_files(_make_repo_msg())

    assert finalizer.finalize_calls == [10]


@pytest.mark.asyncio
async def test_retry_failed_files_raises_and_marks_repo_failed_when_tarball_download_fails() -> None:
    session = FakeAsyncSession(
        users={1: _make_user()}, registered_repo=RegisteredRepo(repo_id=10, status=RepoIndexStatus.FAILED)
    )
    session.added.append(IndexedFile(repo_id=10, file_path="broken.py", status=IndexedFileStatus.FAILED))
    github_client = FakeGitHubClient(tarball_error=RuntimeError("download timed out"))
    indexer, _ = _make_indexer(session=session, github_client=github_client)

    with pytest.raises(RuntimeError):
        await indexer.retry_failed_files(_make_repo_msg())

    assert session.registered_repo.status == RepoIndexStatus.FAILED
