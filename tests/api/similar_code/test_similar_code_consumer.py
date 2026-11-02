"""
    Tests for SimilarCodeRequestConsumer against fakes: no real DB, no real Kafka, no real pipeline.
    The duplicate check is replaced by a recording fake (covered in tests/pipeline/test_dry_check.py),
    so these exercise the consumer's own status handling and recovery only.
"""
import uuid
from datetime import datetime

import pytest

from api.db.models.registered_repo import RegisteredRepo, RepoIndexStatus
from api.db.models.similar_code_search import SimilarCodeSearch, SimilarCodeSearchStatus
from api.schemas.similar_code import SimilarCodeRequestedMessage
from api.similar_code import similar_code_consumer
from api.similar_code.similar_code_consumer import (
    CHUNKING_FAILED_DETAIL,
    INTAKE_REJECTED_DETAIL,
    SEARCH_UNAVAILABLE_DETAIL,
    SimilarCodeConsumerDependencies,
    SimilarCodeMessageParseError,
    SimilarCodeRequestConsumer,
)
from code_reviewer.guardrails.errors import GuardrailsInvocationError, IntakeRejectedError
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.rag.dry_judge import DryJudgeInvocationError
from code_reviewer.rag.errors import ChunkExplanationError, DryMatchingChunkingError, VectorStoreQueryError
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority

SEARCH_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SNIPPET = "def add(a, b):\n    return a + b\n"
SECRET_CAUSE = "connection string postgres://secret"
MESSAGE = SimilarCodeRequestedMessage(search_id=SEARCH_ID, repo_id=10)
DUPLICATE_INCIDENT = Incident(
    priority=Priority.HIGH,
    line_position="1-2",
    description="add is structurally identical to legacy/ops.py:add.",
    advice="Extract the shared logic.",
)


class FakeConsumerRecord:
    def __init__(self, value: bytes = b"", offset: int = 0) -> None:
        self.value = value
        self.offset = offset


class FakeSession:
    def __init__(self, *, search: SimilarCodeSearch | None, repo: RegisteredRepo | None) -> None:
        self.search = search
        self.repo = repo
        self.commit_count = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def scalar(self, statement) -> object | None:
        if statement.column_descriptions[0]["entity"] is SimilarCodeSearch:
            return self.search
        return self.repo

    async def commit(self) -> None:
        self.commit_count += 1


class FakeDatabaseEngine:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def new_session(self) -> FakeSession:
        return self._session


class UnreachableDatabaseEngine:
    def new_session(self) -> FakeSession:
        raise ConnectionError("database is down")


class FakeSnippetCheck:
    def __init__(self, *, incidents: list[Incident] | None = None, error: Exception | None = None) -> None:
        self._incidents = incidents or []
        self._error = error
        self.calls: list[tuple[RepoData, str]] = []

    def __call__(self, agents_container: object, repo_data: RepoData, content: str) -> AgentReviewEntry:
        self.calls.append((repo_data, content))
        if self._error:
            raise self._error
        return AgentReviewEntry(file_path="<submitted snippet>", code_key=CodeKey.DRY, incidents=self._incidents)


def _make_search(**overrides) -> SimilarCodeSearch:
    defaults = {
        "id": 1,
        "search_id": SEARCH_ID,
        "repo_id": 10,
        "requested_by_user_id": 1,
        "code": SNIPPET,
        "status": SimilarCodeSearchStatus.PENDING,
        "status_reason": None,
        "incidents": None,
        "created_at": datetime(2026, 1, 1),
        "completed_at": None,
    }
    defaults.update(overrides)
    return SimilarCodeSearch(**defaults)


def _make_repo() -> RegisteredRepo:
    return RegisteredRepo(
        id=1,
        repo_id=10,
        owner_id=99,
        full_name="octocat/hello-world",
        default_branch="main",
        branch="main",
        commit_sha="abc123",
        registered_by_user_id=1,
        status=RepoIndexStatus.COMPLETED,
        created_at=datetime(2026, 1, 1),
    )


def _make_consumer(engine: object) -> SimilarCodeRequestConsumer:
    return SimilarCodeRequestConsumer(SimilarCodeConsumerDependencies(database_engine=engine, agents_container=object()))


def _install_check(monkeypatch: pytest.MonkeyPatch, check: FakeSnippetCheck) -> None:
    monkeypatch.setattr(similar_code_consumer, "check_snippet_for_duplicates", check)


async def _handle(search: SimilarCodeSearch | None, repo: RegisteredRepo | None = None) -> None:
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=search, repo=repo or _make_repo())))
    await consumer._handle_parsed_message(MESSAGE, FakeConsumerRecord(), None)


@pytest.mark.asyncio
async def test_search_with_a_duplicate_completes_with_its_incidents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the incidents DRY reports are stored for the poller."""
    _install_check(monkeypatch, FakeSnippetCheck(incidents=[DUPLICATE_INCIDENT]))
    search = _make_search()

    await _handle(search)

    assert (search.status, search.incidents) == (
        SimilarCodeSearchStatus.COMPLETED,
        [DUPLICATE_INCIDENT.model_dump(mode="json")],
    )


@pytest.mark.asyncio
async def test_search_with_nothing_similar_completes_with_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a clean answer is an empty list, which a poller can tell apart from a search that has not finished."""
    _install_check(monkeypatch, FakeSnippetCheck())
    search = _make_search()

    await _handle(search)

    assert search.incidents == []


@pytest.mark.asyncio
async def test_finished_search_drops_the_stored_snippet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify user code is not kept once the answer exists."""
    _install_check(monkeypatch, FakeSnippetCheck())
    search = _make_search()

    await _handle(search)

    assert search.code is None


@pytest.mark.asyncio
async def test_finished_search_records_when_it_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a finished search carries its completion time."""
    _install_check(monkeypatch, FakeSnippetCheck())
    search = _make_search()

    await _handle(search)

    assert search.completed_at is not None


@pytest.mark.asyncio
async def test_search_checks_the_stored_snippet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the worker checks exactly the code that was submitted."""
    check = FakeSnippetCheck()
    _install_check(monkeypatch, check)

    await _handle(_make_search())

    assert check.calls[0][1] == SNIPPET


@pytest.mark.asyncio
async def test_search_is_scoped_to_the_repo_and_its_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the search runs against this repo's history only, never another tenant's."""
    check = FakeSnippetCheck()
    _install_check(monkeypatch, check)

    await _handle(_make_search())

    assert check.calls[0][0] == RepoData(repo_id="10", commit_sha="abc123", owner_id="99")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,reason",
    [
        (IntakeRejectedError(SECRET_CAUSE), INTAKE_REJECTED_DETAIL),
        (DryMatchingChunkingError(SECRET_CAUSE), CHUNKING_FAILED_DETAIL),
        (FileTooLargeError("File is 2000 lines"), "File is 2000 lines"),
        (SubmissionTooLargeError("Submission is too long"), "Submission is too long"),
    ],
)
async def test_refused_snippet_is_rejected_with_the_reason(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    """Verify each reason a snippet is refused reaches the poller, with guardrail internals replaced by a fixed message."""
    _install_check(monkeypatch, FakeSnippetCheck(error=error))
    search = _make_search()

    await _handle(search)

    assert (search.status, search.status_reason) == (SimilarCodeSearchStatus.REJECTED, reason)


@pytest.mark.asyncio
async def test_rejected_search_drops_the_stored_snippet(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a refused snippet is not kept either."""
    _install_check(monkeypatch, FakeSnippetCheck(error=IntakeRejectedError("injection")))
    search = _make_search()

    await _handle(search)

    assert search.code is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        VectorStoreQueryError(SECRET_CAUSE),
        ChunkExplanationError(SECRET_CAUSE),
        DryJudgeInvocationError(SECRET_CAUSE),
        GuardrailsInvocationError(SECRET_CAUSE),
        TimeoutError(SECRET_CAUSE),
    ],
    ids=lambda error: type(error).__name__,
)
async def test_search_hit_by_an_infrastructure_failure_fails_with_a_fixed_reason(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Verify an outage or model failure is `failed` (retry later), distinct from a refused snippet."""
    _install_check(monkeypatch, FakeSnippetCheck(error=error))
    search = _make_search()

    await _handle(search)

    assert (search.status, search.status_reason) == (SimilarCodeSearchStatus.FAILED, SEARCH_UNAVAILABLE_DETAIL)


@pytest.mark.asyncio
async def test_failed_search_does_not_leak_the_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the poller never sees the internal error text."""
    _install_check(monkeypatch, FakeSnippetCheck(error=VectorStoreQueryError(SECRET_CAUSE)))
    search = _make_search()

    await _handle(search)

    assert SECRET_CAUSE not in search.status_reason


@pytest.mark.asyncio
async def test_unexpected_error_still_fails_the_search_so_the_poller_stops_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a crash the worker did not anticipate does not leave the search running forever."""
    _install_check(monkeypatch, FakeSnippetCheck(error=RuntimeError("bug")))
    search = _make_search()

    await _handle(search)

    assert search.status == SimilarCodeSearchStatus.FAILED


@pytest.mark.asyncio
async def test_search_for_a_repo_that_no_longer_exists_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a search whose repo was deleted meanwhile ends as failed."""
    check = FakeSnippetCheck()
    _install_check(monkeypatch, check)
    search = _make_search()
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=search, repo=None)))

    await consumer._handle_parsed_message(MESSAGE, FakeConsumerRecord(), None)

    assert (search.status, check.calls) == (SimilarCodeSearchStatus.FAILED, [])


@pytest.mark.asyncio
async def test_redelivered_message_for_a_finished_search_does_not_run_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Kafka redelivery cannot spend LLM money twice on the same search."""
    check = FakeSnippetCheck()
    _install_check(monkeypatch, check)

    await _handle(_make_search(status=SimilarCodeSearchStatus.COMPLETED, code=None, incidents=[]))

    assert check.calls == []


@pytest.mark.asyncio
async def test_message_for_an_unknown_search_is_ignored_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify one stale message cannot crash the consumer loop."""
    _install_check(monkeypatch, FakeSnippetCheck())

    assert await _handle(None) is None


@pytest.mark.asyncio
async def test_failure_recovery_that_cannot_reach_the_database_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the safety net itself never takes the consumer down when the database is unavailable."""
    _install_check(monkeypatch, FakeSnippetCheck())
    consumer = _make_consumer(UnreachableDatabaseEngine())

    assert await consumer._handle_parsed_message(MESSAGE, FakeConsumerRecord(), None) is None


def test_parse_msg_reads_a_valid_message() -> None:
    """Verify the Kafka record is turned back into the message that was published."""
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=None, repo=None)))

    parsed = consumer._parse_msg(FakeConsumerRecord(value=MESSAGE.model_dump_json().encode()))

    assert parsed == MESSAGE


def test_parse_msg_rejects_a_malformed_message() -> None:
    """Verify garbage on the topic is reported as a parse error, not as a crash."""
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=None, repo=None)))

    with pytest.raises(SimilarCodeMessageParseError):
        consumer._parse_msg(FakeConsumerRecord(value=b"not json"))


@pytest.mark.asyncio
async def test_parse_error_is_logged_without_raising() -> None:
    """Verify a malformed message is skipped so the group can move past it."""
    consumer = _make_consumer(FakeDatabaseEngine(FakeSession(search=None, repo=None)))

    assert await consumer._handle_parse_error(FakeConsumerRecord(), SimilarCodeMessageParseError("bad")) is None
