"""
    When TCASE's dispatch branch falls back to the repo's indexed corpus for
    a source file's test files — both dispatch strategies, fakes only.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.rag.errors import PairingJudgeInvocationError
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.review import CodeKey, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from tests.pipeline.test_dispatch import (
    DISPATCH_FUNCTIONS,
    DispatchFn,
    FakeAgent,
    FakeCodeSimilarityIndex,
    FakeDryJudge,
    FakeEmbeddingIndex,
    FakeRerankPostprocessor,
)

REPO = RepoData(repo_id="1", commit_sha="abc123", owner_id="7")
SOURCE = SubmittedFile(file_path="shop/payment.py", content="def charge(amount):\n    return amount\n")
SUBMITTED_TEST = SubmittedFile(file_path="tests/test_payment.py", content="def test_charge(): ...\n")
CORPUS_TEST = SubmittedFile(file_path="tests/legacy/test_payment.py", content="def test_legacy_charge(): ...\n")


class FakeTestPairingFinder:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[str] = []

    def find_test_files(self, repo_data: RepoData, source_file: SubmittedFile) -> list[SubmittedFile]:
        self.calls.append(source_file.file_path)
        if self._error is not None:
            raise self._error
        return [CORPUS_TEST]


@pytest.fixture
def tcase_agent() -> FakeAgent:
    return FakeAgent(CodeKey.TCASE)


def _container(tcase_agent: FakeAgent, test_pairing_finder: FakeTestPairingFinder) -> AgentsContainer:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    return AgentsContainer(
        file_agents=[],
        chunk_agents=[],
        tcase_agent=tcase_agent,
        dry_judge=FakeDryJudge(),
        rag_manager=FakeEmbeddingIndex(),
        structural_hash_store=StructuralHashStore(engine=engine, schema_name=None),
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=5, postprocessor=FakeRerankPostprocessor()),
        test_pairing_finder=test_pairing_finder,
    )


def _prepared(test_files: list[SubmittedFile], repo_data: RepoData | None = REPO) -> PreparedFile:
    return PreparedFile(source_file=SOURCE, test_files=test_files, size_status=SizeStatus.NORMAL, repo_data=repo_data)


def _tcase_content(tcase_agent: FakeAgent) -> str:
    return tcase_agent.execute_agent_calls[0][0]


@DISPATCH_FUNCTIONS
def test_tcase_reads_corpus_test_files_when_none_were_submitted(dispatch: DispatchFn, tcase_agent: FakeAgent) -> None:
    """Verify a registered repo's indexed test file reaches TCASE when the submission had none."""
    dispatch(_prepared(test_files=[]), _container(tcase_agent, FakeTestPairingFinder()))

    assert _tcase_content(tcase_agent) == Pairing(source_file=SOURCE, test_files=[CORPUS_TEST]).get_content()


@DISPATCH_FUNCTIONS
def test_submitted_test_file_skips_the_corpus_lookup(dispatch: DispatchFn, tcase_agent: FakeAgent) -> None:
    """Verify a test file riding along in the submission is used as-is, with no corpus search."""
    finder = FakeTestPairingFinder()

    dispatch(_prepared(test_files=[SUBMITTED_TEST]), _container(tcase_agent, finder))

    assert finder.calls == []


@DISPATCH_FUNCTIONS
def test_review_without_repo_context_skips_the_corpus_lookup(dispatch: DispatchFn, tcase_agent: FakeAgent) -> None:
    """Verify a standalone snippet review, with no indexed corpus to search, never calls the finder."""
    finder = FakeTestPairingFinder()

    dispatch(_prepared(test_files=[], repo_data=None), _container(tcase_agent, finder))

    assert finder.calls == []


@DISPATCH_FUNCTIONS
def test_failed_corpus_lookup_still_reviews_with_no_test_file(dispatch: DispatchFn, tcase_agent: FakeAgent) -> None:
    """Verify a pairing failure degrades to TCASE's no-test-file path instead of failing TCASE."""
    finder = FakeTestPairingFinder(error=PairingJudgeInvocationError("judge down"))

    dispatch(_prepared(test_files=[]), _container(tcase_agent, finder))

    assert _tcase_content(tcase_agent) == Pairing(source_file=SOURCE, test_files=[]).get_content()
