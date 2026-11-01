"""
    check_snippet_for_duplicates: the guards run before DRY, and DRY's history
    workflow runs against a snippet that is not part of the repo. Fakes only.
"""
from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.pipeline import dry_check
from code_reviewer.pipeline.dry_check import DRY_REQUIRES_REPO_REASON, check_snippet_for_duplicates, run_dry
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralHashStore, StructuralMatch
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, Incident, Priority, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from tests.pipeline.test_dispatch import (
    FakeAgent,
    FakeCodeSimilarityIndex,
    FakeDryJudge,
    FakeEmbeddingIndex,
    FakeRerankPostprocessor,
)

ADD_FUNCTION = "def add(a, b):\n    result = a + b\n    return result\n"
TWO_FUNCTIONS = "def add(a, b):\n    result = a + b\n    return result\n\n\ndef sub(a, b):\n    result = a - b\n    return result\n"
UNPARSEABLE_SNIPPET = "def broken(:\n"
REPO_DATA = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")


@pytest.fixture
def screened_contents(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    screened: list[str] = []
    monkeypatch.setattr(dry_check, "run_intake_screen", lambda content, llm=None: screened.append(content))
    return screened


@pytest.fixture
def dry_judge() -> FakeDryJudge:
    return FakeDryJudge()


@pytest.fixture
def rag_manager() -> FakeEmbeddingIndex:
    return FakeEmbeddingIndex()


@pytest.fixture
def structural_hash_store() -> StructuralHashStore:
    return StructuralHashStore(engine=create_engine("sqlite:///:memory:"), schema_name=None)


@pytest.fixture
def container(
    dry_judge: FakeDryJudge, rag_manager: FakeEmbeddingIndex, structural_hash_store: StructuralHashStore
) -> AgentsContainer:
    return AgentsContainer(
        file_agents=[],
        chunk_agents=[],
        tcase_agent=FakeAgent(CodeKey.TCASE),
        dry_judge=dry_judge,
        rag_manager=rag_manager,
        structural_hash_store=structural_hash_store,
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=5, postprocessor=FakeRerankPostprocessor()),
    )


def _check(container: AgentsContainer, content: str) -> AgentReviewEntry:
    return check_snippet_for_duplicates(container, REPO_DATA, content)


def _prepared_file(
    repo_data: RepoData | None,
    content: str = ADD_FUNCTION,
    intra_pr_duplicates: list[list[LocatedChunk]] | None = None,
) -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path="f.py", content=content),
        size_status=SizeStatus.NORMAL,
        repo_data=repo_data,
        intra_pr_duplicates=intra_pr_duplicates or [],
    )


def test_check_snippet_with_exact_copy_in_history_names_the_existing_location(
    container: AgentsContainer, structural_hash_store: StructuralHashStore, screened_contents: list[str]
) -> None:
    """Verify an exact structural copy already indexed in the repo is reported with where it lives."""
    structural_hash_store.index_file(REPO_DATA, "legacy/math_ops.py", ADD_FUNCTION)

    entry = _check(container, ADD_FUNCTION)

    assert "legacy/math_ops.py:add" in entry.incidents[0].description


def test_check_snippet_with_exact_copy_in_history_never_calls_the_judge(
    container: AgentsContainer,
    structural_hash_store: StructuralHashStore,
    dry_judge: FakeDryJudge,
    screened_contents: list[str],
) -> None:
    """Verify an exact structural match is templated, since the hash already proves the duplicate."""
    structural_hash_store.index_file(REPO_DATA, "legacy/math_ops.py", ADD_FUNCTION)

    _check(container, ADD_FUNCTION)

    assert dry_judge.judge_calls == []


def test_check_snippet_with_semantic_match_reports_the_judges_incident(
    container: AgentsContainer,
    rag_manager: FakeEmbeddingIndex,
    dry_judge: FakeDryJudge,
    screened_contents: list[str],
) -> None:
    """Verify a fuzzy candidate is confirmed by the judge, and the judge's verdict is the finding."""
    rag_manager._matches = [
        SimilarChunk(
            file_path="legacy/sums.py", chunk_name="total", start_line=1, end_line=2, text="t", score=0.9, code="def total(v): ..."
        )
    ]
    dry_judge._incidents = [Incident(priority=Priority.MEDIUM, line_position="1-1", description="d", advice="a")]

    entry = _check(container, ADD_FUNCTION)

    assert entry.incidents[0].description == "d"


def test_check_snippet_with_no_match_returns_a_clean_entry(
    container: AgentsContainer, screened_contents: list[str]
) -> None:
    """Verify a snippet nothing in the repo resembles produces no incidents."""
    entry = _check(container, ADD_FUNCTION)

    assert entry.incidents == []


def test_check_snippet_with_no_match_is_not_reported_as_skipped(
    container: AgentsContainer, screened_contents: list[str]
) -> None:
    """Verify a clean answer is distinguishable from DRY not having run."""
    entry = _check(container, ADD_FUNCTION)

    assert entry.skipped is False


def test_check_snippet_screens_the_submitted_content(
    container: AgentsContainer, screened_contents: list[str]
) -> None:
    """Verify the intake screen sees exactly what the caller submitted."""
    _check(container, ADD_FUNCTION)

    assert screened_contents == [ADD_FUNCTION]


def test_check_snippet_rejected_by_the_intake_screen_raises(
    container: AgentsContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a snippet that fails the intake screen is refused before any search."""

    def reject(content: str, llm: object = None) -> None:
        raise IntakeRejectedError("prompt injection")

    monkeypatch.setattr(dry_check, "run_intake_screen", reject)

    with pytest.raises(IntakeRejectedError):
        _check(container, ADD_FUNCTION)


def test_check_snippet_over_the_character_cap_raises(
    container: AgentsContainer, screened_contents: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a snippet longer than the raw character cap is refused."""
    monkeypatch.setattr(get_settings(), "max_submission_characters", 10)

    with pytest.raises(SubmissionTooLargeError):
        _check(container, ADD_FUNCTION)


def test_check_snippet_over_the_character_cap_never_reaches_the_intake_screen(
    container: AgentsContainer, screened_contents: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the free length check rejects first, so an oversized snippet never costs an LLM call."""
    monkeypatch.setattr(get_settings(), "max_submission_characters", 10)

    with pytest.raises(SubmissionTooLargeError):
        _check(container, ADD_FUNCTION)

    assert screened_contents == []


def test_check_snippet_over_the_line_cap_raises(
    container: AgentsContainer, screened_contents: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify a snippet with more lines than the file cap is refused."""
    monkeypatch.setattr(get_settings(), "max_file_lines", 1)

    with pytest.raises(FileTooLargeError):
        _check(container, ADD_FUNCTION)


def test_check_snippet_that_cannot_be_split_raises(
    container: AgentsContainer, screened_contents: list[str]
) -> None:
    """Verify code the splitter cannot parse is reported as such, never as a clean result."""
    with pytest.raises(DryMatchingChunkingError):
        _check(container, UNPARSEABLE_SNIPPET)


def test_run_dry_with_no_repo_is_skipped_with_the_repo_requirement_reason(container: AgentsContainer) -> None:
    """Verify DRY reports it did not run, instead of a clean result, when there is no repo history to compare against."""
    entry = run_dry(container, _prepared_file(repo_data=None))

    assert entry.skip_reason == DRY_REQUIRES_REPO_REASON


def test_run_dry_with_intra_pr_duplicates_reports_them_without_a_history_match(container: AgentsContainer) -> None:
    """Verify a duplicate shared with another file in the same PR is reported even when the repo history has none."""
    group = [
        LocatedChunk(StructuralMatch(file_path="f.py", chunk_name="foo", start_line=1, end_line=3), ADD_FUNCTION),
        LocatedChunk(StructuralMatch(file_path="other.py", chunk_name="bar", start_line=5, end_line=7), ADD_FUNCTION),
    ]

    entry = run_dry(container, _prepared_file(REPO_DATA, intra_pr_duplicates=[group]))

    assert "other.py:bar (lines 5-7)" in entry.incidents[0].description


def test_run_dry_reports_every_chunk_of_the_file_that_has_a_history_match(
    container: AgentsContainer, structural_hash_store: StructuralHashStore
) -> None:
    """Verify each function in the submitted file is searched, not only the first one."""
    structural_hash_store.index_file(REPO_DATA, "legacy/ops.py", TWO_FUNCTIONS)

    entry = run_dry(container, _prepared_file(REPO_DATA, content=TWO_FUNCTIONS))

    assert len(entry.incidents) == 2


def test_run_dry_ignores_a_match_the_reranker_dropped_entirely(
    container: AgentsContainer, rag_manager: FakeEmbeddingIndex, dry_judge: FakeDryJudge
) -> None:
    """Verify a chunk whose every candidate was ranked out is clean, and never reaches the judge."""
    rag_manager._matches = [
        SimilarChunk(
            file_path="legacy/sums.py", chunk_name="total", start_line=1, end_line=2, text="t", score=0.9, code="def total(v): ..."
        )
    ]
    reranker_dropping_everything = HistoryMatchReranker(max_candidates=0, postprocessor=FakeRerankPostprocessor())
    dropping_container = replace(container, history_match_reranker=reranker_dropping_everything)

    run_dry(dropping_container, _prepared_file(REPO_DATA))

    assert dry_judge.judge_calls == []
