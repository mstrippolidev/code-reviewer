"""
    Tests for ExemplarPromotionConsumer against fakes: no real DB, no real Kafka, no real judge panel.
    The fake session answers `scalar` calls in the order the consumer makes them: repo, file, then the
    two "already decided" checks.
"""
import uuid

import pytest

from api.db.models.exemplar_promotion import ExemplarPromotion, PromotionOutcome
from api.db.models.indexed_file import IndexedFile, IndexedFileStatus
from api.db.models.registered_repo import RegisteredRepo
from api.exemplars.promotion_consumer import ExemplarPromotionConsumer, ExemplarPromotionConsumerDependencies
from api.exemplars.topics import EXEMPLAR_PROMOTION_REQUESTED_DLQ
from api.schemas.exemplars import ExemplarPromotionRequestedMessage
from code_reviewer.rag.exemplar_promotion import ExemplarCandidate
from code_reviewer.rag.exemplar_promotion import PromotionOutcome as PanelOutcome
from code_reviewer.schemas.review import CodeKey


class FakeSession:
    def __init__(self, scalar_results: list) -> None:
        self._scalar_results = list(scalar_results)
        self.added: list[ExemplarPromotion] = []
        self.commits = 0

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def scalar(self, statement) -> object:
        return self._scalar_results.pop(0)

    def add(self, row: ExemplarPromotion) -> None:
        self.added.append(row)

    async def commit(self) -> None:
        self.commits += 1


class FakeDatabaseEngine:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def new_session(self) -> FakeSession:
        return self._session


class FakePromoter:
    def __init__(self, outcome: PanelOutcome | None = None, error: Exception | None = None) -> None:
        self._outcome = outcome
        self._error = error
        self.candidates: list[ExemplarCandidate] = []

    def promote(self, candidate: ExemplarCandidate) -> PanelOutcome:
        self.candidates.append(candidate)
        if self._error:
            raise self._error
        return self._outcome


class FakeDlqProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, bytes | None, Exception]] = []

    async def publish_to_dlq(self, dlq_topic: str, payload: bytes, key: bytes | None, error: Exception) -> None:
        self.published.append((dlq_topic, payload, key, error))


class FakeConsumerRecord:
    def __init__(self, value: bytes, key: bytes | None = None, offset: int = 0) -> None:
        self.value = value
        self.key = key
        self.offset = offset


def _message() -> ExemplarPromotionRequestedMessage:
    return ExemplarPromotionRequestedMessage(
        review_id=uuid.uuid4(), repo_id=10, file_path="a.py", code_key=CodeKey.SOLID1
    )


def _repo() -> RegisteredRepo:
    return RegisteredRepo(repo_id=10, owner_id=99, commit_sha="abc123")


def _indexed_file() -> IndexedFile:
    return IndexedFile(repo_id=10, file_path="a.py", status=IndexedFileStatus.INDEXED, content="class A: ...\n")


def _consumer(
    session: FakeSession, promoter: FakePromoter, dlq_producer: FakeDlqProducer | None = None
) -> ExemplarPromotionConsumer:
    dependencies = ExemplarPromotionConsumerDependencies(
        database_engine=FakeDatabaseEngine(session),
        promoter=promoter,
        dlq_producer=dlq_producer or FakeDlqProducer(),
    )
    return ExemplarPromotionConsumer(dependencies, "localhost:9092")


async def _handle(consumer: ExemplarPromotionConsumer, message: ExemplarPromotionRequestedMessage) -> None:
    record = FakeConsumerRecord(value=message.model_dump_json().encode(), key=b"10")
    await consumer._handle_parsed_message(message, record, consumer=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_outcome", list(PanelOutcome))
async def test_each_panel_outcome_is_stored_for_the_file_content(panel_outcome: PanelOutcome) -> None:
    """Verify promoted, rejected and split votes are all recorded, so a file is never judged twice."""
    session = FakeSession([_repo(), _indexed_file(), None, None])
    promoter = FakePromoter(outcome=panel_outcome)

    await _handle(_consumer(session, promoter), _message())

    stored = session.added[0]
    assert (stored.repo_id, stored.file_path, stored.code_key) == (10, "a.py", "SOLID1")
    assert stored.outcome is PromotionOutcome(panel_outcome.value)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_the_whole_file_is_put_to_the_panel_scoped_to_its_repo() -> None:
    """Verify the candidate is the indexed file's content under the repo's own scoping."""
    session = FakeSession([_repo(), _indexed_file(), None, None])
    promoter = FakePromoter(outcome=PanelOutcome.REJECTED)

    await _handle(_consumer(session, promoter), _message())

    candidate = promoter.candidates[0]
    assert candidate.source.code == "class A: ...\n"
    assert (candidate.repo_data.repo_id, candidate.repo_data.owner_id) == ("10", "99")
    assert candidate.code_key is CodeKey.SOLID1


@pytest.mark.asyncio
@pytest.mark.parametrize("scalar_results", [[None, _indexed_file()], [_repo(), None]])
async def test_a_repo_or_file_that_is_gone_is_skipped_quietly(scalar_results: list) -> None:
    """Verify a nomination for a deleted repo or a no-longer-indexed file costs no panel call and no DLQ entry."""
    session = FakeSession(scalar_results)
    promoter = FakePromoter(outcome=PanelOutcome.PROMOTED)
    dlq_producer = FakeDlqProducer()

    await _handle(_consumer(session, promoter, dlq_producer), _message())

    assert promoter.candidates == []
    assert dlq_producer.published == []


@pytest.mark.asyncio
async def test_a_repo_that_already_has_an_exemplar_for_the_agent_is_not_judged_again() -> None:
    """Verify the one-exemplar-per-repo-and-agent rule stops the panel before it is paid."""
    session = FakeSession([_repo(), _indexed_file(), 5])
    promoter = FakePromoter(outcome=PanelOutcome.PROMOTED)

    await _handle(_consumer(session, promoter), _message())

    assert promoter.candidates == []
    assert session.added == []


@pytest.mark.asyncio
async def test_content_that_was_already_judged_is_not_judged_again() -> None:
    """Verify a rejected or split file is remembered by its content hash."""
    session = FakeSession([_repo(), _indexed_file(), None, 7])
    promoter = FakePromoter(outcome=PanelOutcome.PROMOTED)

    await _handle(_consumer(session, promoter), _message())

    assert promoter.candidates == []
    assert session.added == []


@pytest.mark.asyncio
async def test_a_failed_vote_goes_to_the_dead_letter_topic_and_stores_nothing() -> None:
    """Verify a panel failure is not recorded as a decision, so the nomination can be retried from the DLQ."""
    session = FakeSession([_repo(), _indexed_file(), None, None])
    promoter = FakePromoter(error=RuntimeError("judge down"))
    dlq_producer = FakeDlqProducer()

    await _handle(_consumer(session, promoter, dlq_producer), _message())

    assert [topic for topic, *_ in dlq_producer.published] == [EXEMPLAR_PROMOTION_REQUESTED_DLQ]
    assert session.added == []


@pytest.mark.asyncio
async def test_an_unparseable_message_goes_to_the_dead_letter_topic() -> None:
    """Verify a poisoned message is forwarded so the group can move past it."""
    dlq_producer = FakeDlqProducer()
    consumer = _consumer(FakeSession([]), FakePromoter(), dlq_producer)
    record = FakeConsumerRecord(value=b"not json", key=b"10")

    await consumer._handle_parse_error(record, ValueError("bad"))

    assert [topic for topic, *_ in dlq_producer.published] == [EXEMPLAR_PROMOTION_REQUESTED_DLQ]
