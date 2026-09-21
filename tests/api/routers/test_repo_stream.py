"""
    Tests for GET /api/repos/{repo_id}/files/stream against fakes: no real DB, no real Kafka.

    Uses httpx.AsyncClient + ASGITransport instead of the sync TestClient used elsewhere in this
    router's tests, since the concurrency tests need to publish onto the broadcaster while a
    stream is still open -- that requires running the client read as its own asyncio task rather
    than a single blocking call.
"""
import asyncio
import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.user import User
from api.dependencies import get_current_user, get_db_session
from api.indexing.repo_progress_broadcaster import RepoProgressBroadcaster
from api.routers.repos import router as repos_router
from api.schemas.repos import RepoFileProgressMessage, RepoStatusProgressMessage

_TIMEOUT = 2


class _ScalarsResult:
    def __init__(self, rows: list[RegisteredRepo | IndexedFile]) -> None:
        self._rows = rows

    def all(self) -> list[RegisteredRepo | IndexedFile]:
        return self._rows


class FakeAsyncSession:
    def __init__(
        self, existing: list[RegisteredRepo] | None = None, indexed_files: list[IndexedFile] | None = None
    ) -> None:
        self._rows: list[RegisteredRepo] = list(existing or [])
        self._indexed_files: list[IndexedFile] = list(indexed_files or [])

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    def _rows_for(self, statement) -> list[RegisteredRepo | IndexedFile]:
        entity = statement.column_descriptions[0]["entity"]
        rows = self._indexed_files if entity is IndexedFile else self._rows
        requested_repo_id = next(iter(statement.compile().params.values()), None)
        if requested_repo_id is None:
            return rows
        return [row for row in rows if row.repo_id == requested_repo_id]

    async def scalar(self, statement) -> RegisteredRepo | IndexedFile | None:
        rows = self._rows_for(statement)
        return rows[0] if rows else None

    async def scalars(self, statement) -> _ScalarsResult:
        return _ScalarsResult(self._rows_for(statement))


class PublishDuringSnapshotQuerySession(FakeAsyncSession):
    """Publishes a live event the moment _get_indexed_files' query resolves, simulating a file
    finishing in the exact gap between subscribing and reading the snapshot."""

    def __init__(self, *, broadcaster: RepoProgressBroadcaster, live_event: RepoFileProgressMessage, **kwargs) -> None:
        super().__init__(**kwargs)
        self._broadcaster = broadcaster
        self._live_event = live_event
        self._published = False

    async def scalars(self, statement) -> _ScalarsResult:
        result = await super().scalars(statement)
        if not self._published:
            self._published = True
            await self._broadcaster.publish(self._live_event.repo_id, self._live_event)
        return result


def _make_registered_repo(**overrides) -> RegisteredRepo:
    defaults = {
        "id": 1,
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "default_branch": "main",
        "registered_by_user_id": 1,
        "status": RepoIndexStatus.INDEXING,
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


def _make_user() -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token=b"unused",
        github_granted_scopes="repo",
    )


def _build_app(*, session: FakeAsyncSession, broadcaster: RepoProgressBroadcaster | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(repos_router)
    app.state.repo_progress_broadcaster = broadcaster or RepoProgressBroadcaster()

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    return app


def _client_for(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_events(text: str) -> list[dict]:
    events = []
    event_type = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append({"type": event_type, "data": json.loads(line[len("data:") :].strip())})
        elif line == "":
            event_type = "message"
    return events


def _file_events(text: str) -> list[dict]:
    return [event["data"] for event in _parse_events(text) if event["type"] == "file"]


def _status_events(text: str) -> list[dict]:
    return [event["data"] for event in _parse_events(text) if event["type"] == "status"]


@pytest.mark.asyncio
async def test_stream_returns_404_for_an_unregistered_repo() -> None:
    app = _build_app(session=FakeAsyncSession())

    async with _client_for(app) as client:
        response = await asyncio.wait_for(client.get("/api/repos/999/files/stream"), timeout=_TIMEOUT)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_sends_the_current_snapshot_as_indexed_file_shaped_events() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    files = [
        _make_indexed_file(id=1, file_path="a.py", status=IndexedFileStatus.INDEXED),
        _make_indexed_file(id=2, file_path="b.py", status=IndexedFileStatus.FAILED, status_reason="boom"),
    ]
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=files))

    async with _client_for(app) as client:
        response = await asyncio.wait_for(client.get("/api/repos/10/files/stream"), timeout=_TIMEOUT)

    events = _file_events(response.text)
    assert {event["file_path"] for event in events} == {"a.py", "b.py"}
    assert all("repo_id" not in event for event in events)


@pytest.mark.asyncio
async def test_stream_closes_immediately_when_the_repo_is_already_completed() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.COMPLETED)
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]))

    async with _client_for(app) as client:
        response = await asyncio.wait_for(client.get("/api/repos/10/files/stream"), timeout=_TIMEOUT)

    assert response.status_code == 200
    assert _file_events(response.text) == []
    assert _status_events(response.text) == [
        {"repo_id": 10, "status": "completed", "status_reason": None, "total_files_expected": None}
    ]


@pytest.mark.asyncio
async def test_stream_closes_immediately_when_the_repo_is_already_failed() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.FAILED)
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]))

    async with _client_for(app) as client:
        response = await asyncio.wait_for(client.get("/api/repos/10/files/stream"), timeout=_TIMEOUT)

    assert response.status_code == 200
    assert _file_events(response.text) == []
    assert _status_events(response.text) == [
        {"repo_id": 10, "status": "failed", "status_reason": None, "total_files_expected": None}
    ]


@pytest.mark.asyncio
async def test_stream_relays_a_live_file_progress_event_after_the_snapshot() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        live_event = RepoFileProgressMessage(
            repo_id=10, file_path="new.py", status=IndexedFileStatus.INDEXED, status_reason=None
        )
        await broadcaster.publish(10, live_event)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        response = await asyncio.wait_for(task, timeout=_TIMEOUT)

    events = _file_events(response.text)
    assert events == [{"repo_id": 10, "file_path": "new.py", "status": "indexed", "status_reason": None}]


@pytest.mark.asyncio
async def test_stream_does_not_close_on_a_non_terminal_status_event() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.INDEXING, status_reason=None)
        )
        await asyncio.sleep(0.05)
        assert task.done() is False
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.FAILED, status_reason="oops")
        )
        response = await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert _file_events(response.text) == []


@pytest.mark.asyncio
async def test_stream_forwards_the_terminal_status_event_before_closing() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        response = await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert response.status_code == 200
    assert _file_events(response.text) == []
    assert _status_events(response.text)[-1] == {
        "repo_id": 10, "status": "completed", "status_reason": None, "total_files_expected": None
    }


@pytest.mark.asyncio
async def test_stream_subscribes_before_querying_the_snapshot() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    live_event = RepoFileProgressMessage(
        repo_id=10, file_path="mid-flight.py", status=IndexedFileStatus.INDEXED, status_reason=None
    )
    session = PublishDuringSnapshotQuerySession(
        broadcaster=broadcaster, live_event=live_event, existing=[repo], indexed_files=[]
    )
    app = _build_app(session=session, broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        response = await asyncio.wait_for(task, timeout=_TIMEOUT)

    events = _file_events(response.text)
    assert events == [{"repo_id": 10, "file_path": "mid-flight.py", "status": "indexed", "status_reason": None}]


@pytest.mark.asyncio
async def test_stream_unsubscribes_after_the_repo_finishes() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert 10 not in broadcaster._subscribers


@pytest.mark.asyncio
async def test_stream_unsubscribes_when_the_client_disconnects_before_any_terminal_event() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=_TIMEOUT)

    assert 10 not in broadcaster._subscribers


@pytest.mark.asyncio
async def test_stream_delivers_a_live_event_to_multiple_concurrent_subscribers_of_the_same_repo() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        first_task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        second_task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        assert len(broadcaster._subscribers[10]) == 2
        live_event = RepoFileProgressMessage(
            repo_id=10, file_path="shared.py", status=IndexedFileStatus.INDEXED, status_reason=None
        )
        await broadcaster.publish(10, live_event)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        first_response, second_response = await asyncio.wait_for(
            asyncio.gather(first_task, second_task), timeout=_TIMEOUT
        )

    for response in (first_response, second_response):
        events = _file_events(response.text)
        assert events == [{"repo_id": 10, "file_path": "shared.py", "status": "indexed", "status_reason": None}]
    assert 10 not in broadcaster._subscribers


@pytest.mark.asyncio
async def test_stream_does_not_deliver_an_event_to_a_different_repos_concurrent_subscriber() -> None:
    repo_ten = _make_registered_repo(repo_id=10, status=RepoIndexStatus.INDEXING)
    repo_twenty = _make_registered_repo(id=2, repo_id=20, status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(
        session=FakeAsyncSession(existing=[repo_ten, repo_twenty], indexed_files=[]), broadcaster=broadcaster
    )

    async with _client_for(app) as client:
        task_ten = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        task_twenty = asyncio.create_task(client.get("/api/repos/20/files/stream"))
        await asyncio.sleep(0.05)
        await broadcaster.publish(
            10, RepoFileProgressMessage(repo_id=10, file_path="only-tens.py", status=IndexedFileStatus.INDEXED, status_reason=None)
        )
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        ten_response = await asyncio.wait_for(task_ten, timeout=_TIMEOUT)
        assert task_twenty.done() is False

        await broadcaster.publish(
            20, RepoStatusProgressMessage(repo_id=20, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        twenty_response = await asyncio.wait_for(task_twenty, timeout=_TIMEOUT)

    assert [event["file_path"] for event in _file_events(ten_response.text)] == ["only-tens.py"]
    assert _file_events(twenty_response.text) == []


@pytest.mark.asyncio
async def test_disconnecting_one_concurrent_subscriber_does_not_affect_another_of_the_same_repo() -> None:
    repo = _make_registered_repo(status=RepoIndexStatus.INDEXING)
    broadcaster = RepoProgressBroadcaster()
    app = _build_app(session=FakeAsyncSession(existing=[repo], indexed_files=[]), broadcaster=broadcaster)

    async with _client_for(app) as client:
        doomed_task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        survivor_task = asyncio.create_task(client.get("/api/repos/10/files/stream"))
        await asyncio.sleep(0.05)
        assert len(broadcaster._subscribers[10]) == 2

        doomed_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(doomed_task, timeout=_TIMEOUT)
        assert len(broadcaster._subscribers[10]) == 1

        live_event = RepoFileProgressMessage(
            repo_id=10, file_path="still-here.py", status=IndexedFileStatus.INDEXED, status_reason=None
        )
        await broadcaster.publish(10, live_event)
        await broadcaster.publish(
            10, RepoStatusProgressMessage(repo_id=10, status=RepoIndexStatus.COMPLETED, status_reason=None)
        )
        survivor_response = await asyncio.wait_for(survivor_task, timeout=_TIMEOUT)

    assert [event["file_path"] for event in _file_events(survivor_response.text)] == ["still-here.py"]
    assert 10 not in broadcaster._subscribers
