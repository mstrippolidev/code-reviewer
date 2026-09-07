"""
    Tests for review_submission — the entry point wiring
    prepare_files_for_pipeline's output into agent dispatch. The intake
    screen is monkeypatched out (LLM-backed, already covered by its own
    tests); agents are faked so these exercise the wiring only.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline import orchestrator
from code_reviewer.pipeline.orchestrator import review_submission
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_judge import JudgeCandidate
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, SizeStatus
from code_reviewer.schemas.submission import SubmittedFile


class FakeEmbeddingIndex:
    """Stands in for LlamaIndexRagManager: returns no semantic matches, never a real vector search."""

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        return []


class FakeCodeSimilarityIndex:
    """Stands in for CodeSimilarityIndex: returns no raw-code or lexical matches, never a real search."""

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[CodeMatch]:
        return []

    def find_lexical_matches(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[LexicalMatch]:
        return []


class FakeRerankPostprocessor:
    """Stands in for the cross-encoder: never actually called here, since
    every fake bucket above returns no candidates to re-rank."""

    def postprocess_nodes(self, nodes, query_bundle=None):
        return nodes


class FakeAgent:
    """Duck-typed stand-in for AgentBase/FileSizeAwareAgentBase/
    CoverageGapAgent — dispatch only ever calls get_agent_key/
    execute_agent/execute_agent_batch."""

    def __init__(self, code_key: CodeKey) -> None:
        self._code_key = code_key

    def get_agent_key(self) -> CodeKey:
        return self._code_key

    def execute_agent(self, code: str, file_path: str | None = None, size_status: SizeStatus | None = None) -> AgentOutput:
        entry = AgentReviewEntry(file_path=file_path, code_key=self._code_key, incidents=[])
        return AgentOutput(review=[entry])

    def execute_agent_batch(self, chunks: list[str], file_path: str | None = None) -> list[AgentOutput]:
        return [self.execute_agent(chunk, file_path) for chunk in chunks]


class FakeDryJudge:
    """Stands in for DryJudge — never called by these tests, since none
    of them give DRY any evidence to judge."""

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        return []


@pytest.fixture
def container() -> AgentsContainer:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    return AgentsContainer(
        file_agents=[FakeAgent(CodeKey.COH)],
        chunk_agents=[FakeAgent(CodeKey.VAR)],
        tcase_agent=FakeAgent(CodeKey.TCASE),
        dry_judge=FakeDryJudge(),
        rag_manager=FakeEmbeddingIndex(),
        structural_hash_store=StructuralHashStore(engine=engine, schema_name=None),
        code_similarity_index=FakeCodeSimilarityIndex(),
        history_match_reranker=HistoryMatchReranker(max_candidates=100, postprocessor=FakeRerankPostprocessor()),
    )


@pytest.fixture(autouse=True)
def skip_intake_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "run_intake_screen", lambda content: None)


def _file(file_path: str, content: str = "x = 1\n") -> SubmittedFile:
    return SubmittedFile(file_path=file_path, content=content)


def test_returns_one_entry_per_agent_for_a_single_file(container: AgentsContainer) -> None:
    entries, skipped = review_submission([_file("a.py")], container)

    assert {entry.code_key for entry in entries} == {CodeKey.COH, CodeKey.VAR, CodeKey.TCASE, CodeKey.DRY}
    assert skipped == []


def test_flattens_entries_across_multiple_files(container: AgentsContainer) -> None:
    entries, _ = review_submission([_file("a.py"), _file("b.py")], container)

    assert {entry.file_path for entry in entries} == {"a.py", "b.py"}
    assert len(entries) == 8


def test_no_files_returns_no_entries_and_no_skips(container: AgentsContainer) -> None:
    entries, skipped = review_submission([], container)

    assert entries == []
    assert skipped == []


def test_intra_pr_duplicate_groups_are_attached_per_file() -> None:
    """Verify a structural duplicate spanning two files is computed once
    and attached to both files' own PreparedFile, not just one."""
    add_function = "def add(a, b):\n    return a + b\n"
    files = [_file("a.py", add_function), _file("b.py", add_function)]

    prepared_files, _ = orchestrator.prepare_files_for_pipeline(files)

    assert all(len(prepared.intra_pr_duplicates) == 1 for prepared in prepared_files)
    touched_files = {
        located.match.file_path
        for prepared in prepared_files
        for group in prepared.intra_pr_duplicates
        for located in group
    }
    assert touched_files == {"a.py", "b.py"}


def test_intra_pr_duplicate_detection_degrades_gracefully_on_unparseable_file() -> None:
    """Verify one file that can't be chunked doesn't crash the whole
    submission — every file still gets prepared, just with no intra-PR evidence."""
    files = [_file("broken.py", "def broken(:\n    pass\n"), _file("a.py", "x = 1\n")]

    prepared_files, _ = orchestrator.prepare_files_for_pipeline(files)

    assert len(prepared_files) == 2
    assert all(prepared.intra_pr_duplicates == [] for prepared in prepared_files)


def test_file_over_the_hard_line_limit_is_skipped_not_reviewed(
    container: AgentsContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_file_lines", 10)
    oversized = _file("too_big.py", content="x = 1\n" * 20)

    entries, skipped = review_submission([oversized], container)

    assert entries == []
    assert [skipped_file.file_path for skipped_file in skipped] == ["too_big.py"]
