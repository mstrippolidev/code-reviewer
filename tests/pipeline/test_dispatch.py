"""
    Tests for dispatch's own wiring — which agents get called, with what
    content, and how chunked results get merged — for both the sequential
    (review_file) and RunnableParallel-fanned-out (review_file_runnable)
    dispatch strategies. Agents are faked so these exercise dispatch's
    logic only, never a real LLM.
"""
import asyncio
from typing import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.pipeline.dispatch import review_file, review_file_runnable
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_judge import JudgeCandidate
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralHashStore, StructuralMatch
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

SOURCE_WITH_TWO_FUNCTIONS = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n"
ADD_FUNCTION = "def add(a, b):\n    result = a + b\n    return result\n"


class FakeEmbeddingIndex:
    """Stands in for LlamaIndexRagManager: returns a canned list of
    semantic matches, never a real vector search."""

    def __init__(self, matches: list[SimilarChunk] | None = None) -> None:
        self._matches = matches if matches is not None else []

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[SimilarChunk]:
        return self._matches


class FakeCodeSimilarityIndex:
    """Stands in for CodeSimilarityIndex: returns canned lists of raw-code
    and lexical matches, never a real search."""

    def __init__(self, code_matches: list[CodeMatch] | None = None, lexical_matches: list[LexicalMatch] | None = None) -> None:
        self._code_matches = code_matches if code_matches is not None else []
        self._lexical_matches = lexical_matches if lexical_matches is not None else []

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[CodeMatch]:
        return self._code_matches

    def find_lexical_matches(self, repo_data: RepoData, code: str, top_k: int = 5) -> list[LexicalMatch]:
        return self._lexical_matches


class FakeRerankPostprocessor:
    """Stands in for the cross-encoder: assigns every candidate the same
    score, so dispatch tests can control who survives without loading a
    real model."""

    def __init__(self, score: float = 1.0) -> None:
        self._score = score

    def postprocess_nodes(self, nodes, query_bundle=None):
        for node in nodes:
            node.score = self._score
        return nodes


class FakeAgent:
    """Stands in for AgentBase/FileSizeAwareAgentBase/CoverageGapAgent —
    dispatch only ever calls get_agent_key/execute_agent/execute_agent_batch,
    so a duck-typed fake is enough to isolate dispatch's own logic."""

    def __init__(self, code_key: CodeKey, rating: int = 100, incidents: list[Incident] | None = None) -> None:
        self._code_key = code_key
        self._rating = rating
        self._incidents = incidents or []
        self.execute_agent_calls: list[tuple] = []
        self.execute_agent_batch_calls: list[tuple] = []

    def get_agent_key(self) -> CodeKey:
        return self._code_key

    def execute_agent(
        self, code: str, file_path: str | None = None, review_meta: FileReviewMeta | None = None
    ) -> AgentOutput:
        self.execute_agent_calls.append((code, file_path, review_meta))
        entry = AgentReviewEntry(
            file_path=file_path, code_key=self._code_key, rating=self._rating, incidents=list(self._incidents)
        )
        return AgentOutput(review=[entry])

    def execute_agent_batch(self, chunks: list[str], file_path: str | None = None) -> list[AgentOutput]:
        self.execute_agent_batch_calls.append((chunks, file_path))
        return [
            AgentOutput(
                review=[
                    AgentReviewEntry(
                        file_path=file_path, code_key=self._code_key, rating=self._rating, incidents=list(self._incidents)
                    )
                ]
            )
            for _ in chunks
        ]


class FakeDryJudge:
    """Stands in for DryJudge: records what it was asked to judge and
    returns a canned list of confirmed incidents."""

    def __init__(self, incidents: list[Incident] | None = None) -> None:
        self._incidents = incidents if incidents is not None else []
        self.judge_calls: list[tuple[str, list[JudgeCandidate]]] = []

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        self.judge_calls.append((query_code, candidates))
        return list(self._incidents)


@pytest.fixture
def file_agent() -> FakeAgent:
    return FakeAgent(CodeKey.COH)


@pytest.fixture
def cmplx_agent() -> FakeAgent:
    return FakeAgent(CodeKey.CMPLX)


@pytest.fixture
def var_agent() -> FakeAgent:
    return FakeAgent(CodeKey.VAR)


@pytest.fixture
def tcase_agent() -> FakeAgent:
    return FakeAgent(CodeKey.TCASE)


@pytest.fixture
def dry_judge() -> FakeDryJudge:
    return FakeDryJudge()


@pytest.fixture
def structural_hash_store() -> StructuralHashStore:
    """A fresh in-memory SQLite-backed store, isolated per test. StaticPool
    keeps every thread on the same connection — review_file_runnable
    dispatches DRY's branch on a worker thread, and SQLite's default
    per-thread pooling would otherwise hand that thread its own empty
    in-memory database, invisible to whatever this fixture indexed."""
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    return StructuralHashStore(engine=engine, schema_name=None)


@pytest.fixture
def rag_manager() -> FakeEmbeddingIndex:
    return FakeEmbeddingIndex()


@pytest.fixture
def code_similarity_index() -> FakeCodeSimilarityIndex:
    return FakeCodeSimilarityIndex()


@pytest.fixture
def history_match_reranker() -> HistoryMatchReranker:
    return HistoryMatchReranker(max_candidates=100, postprocessor=FakeRerankPostprocessor())


@pytest.fixture
def container(
    file_agent: FakeAgent,
    cmplx_agent: FakeAgent,
    var_agent: FakeAgent,
    tcase_agent: FakeAgent,
    dry_judge: FakeDryJudge,
    rag_manager: FakeEmbeddingIndex,
    structural_hash_store: StructuralHashStore,
    code_similarity_index: FakeCodeSimilarityIndex,
    history_match_reranker: HistoryMatchReranker,
) -> AgentsContainer:
    return AgentsContainer(
        file_agents=[file_agent],
        chunk_agents=[cmplx_agent, var_agent],
        tcase_agent=tcase_agent,
        dry_judge=dry_judge,
        rag_manager=rag_manager,
        structural_hash_store=structural_hash_store,
        code_similarity_index=code_similarity_index,
        history_match_reranker=history_match_reranker,
    )


def _prepared_file(
    size_status: SizeStatus = SizeStatus.NORMAL,
    content: str = "x = 1\n",
    repo_data: RepoData | None = None,
    intra_pr_duplicates: list[list[LocatedChunk]] | None = None,
) -> PreparedFile:
    return PreparedFile(
        source_file=SubmittedFile(file_path="f.py", content=content),
        test_files=[],
        size_status=size_status,
        repo_data=repo_data,
        intra_pr_duplicates=intra_pr_duplicates or [],
    )


DispatchFn = Callable[[PreparedFile, AgentsContainer], list[AgentReviewEntry]]


def _review_file_runnable_sync(prepared_file: PreparedFile, agents_container: AgentsContainer) -> list[AgentReviewEntry]:
    """Bridges the now-async review_file_runnable for the shared
    sync/parallel comparison tests below, so their bodies stay identical
    for both dispatch strategies rather than sprinkling async/await
    through every one of them."""
    return asyncio.run(review_file_runnable(prepared_file, agents_container))


DISPATCH_FUNCTIONS = pytest.mark.parametrize("dispatch", [review_file, _review_file_runnable_sync])


@DISPATCH_FUNCTIONS
def test_returns_one_entry_per_agent_for_a_normal_size_file(dispatch: DispatchFn, container: AgentsContainer) -> None:
    entries = dispatch(_prepared_file(), container)

    assert {entry.code_key for entry in entries} == {
        CodeKey.COH, CodeKey.CMPLX, CodeKey.VAR, CodeKey.TCASE, CodeKey.DRY
    }
    assert len(entries) == 5


@DISPATCH_FUNCTIONS
def test_file_agent_receives_full_content_and_size_status(
    dispatch: DispatchFn, container: AgentsContainer, file_agent: FakeAgent
) -> None:
    prepared = _prepared_file(size_status=SizeStatus.HARD_LIMIT_EXCEEDED, content="x = 1\n")

    dispatch(prepared, container)

    assert file_agent.execute_agent_calls == [
        ("x = 1\n", "f.py", FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED, repo_data=None))
    ]


@DISPATCH_FUNCTIONS
def test_file_agent_receives_repo_data_for_the_evidence_hop(
    dispatch: DispatchFn, container: AgentsContainer, file_agent: FakeAgent
) -> None:
    """Verify repo scoping reaches file agents (ARCH/COUP's tool depends on
    it) via PreparedFile.repo_data, without any dispatch function needing
    a new parameter of its own."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    prepared = _prepared_file(repo_data=repo_data)

    dispatch(prepared, container)

    review_meta = file_agent.execute_agent_calls[0][2]
    assert review_meta.repo_data == repo_data


@DISPATCH_FUNCTIONS
def test_file_agent_receives_no_repo_data_for_a_standalone_review(
    dispatch: DispatchFn, container: AgentsContainer, file_agent: FakeAgent
) -> None:
    """Verify a submission with no repo context (repo_data=None) leaves
    file agents with repo_data=None too, triggering the tool's fallback."""
    prepared = _prepared_file()

    dispatch(prepared, container)

    review_meta = file_agent.execute_agent_calls[0][2]
    assert review_meta.repo_data is None


@DISPATCH_FUNCTIONS
def test_chunk_agent_receives_whole_file_when_size_is_normal(
    dispatch: DispatchFn, container: AgentsContainer, var_agent: FakeAgent
) -> None:
    prepared = _prepared_file(size_status=SizeStatus.NORMAL, content="x = 1\n")

    dispatch(prepared, container)

    assert var_agent.execute_agent_calls == [("x = 1\n", "f.py", None)]
    assert var_agent.execute_agent_batch_calls == []


@DISPATCH_FUNCTIONS
def test_chunk_agent_is_split_and_batched_at_the_soft_limit(
    dispatch: DispatchFn, container: AgentsContainer, var_agent: FakeAgent
) -> None:
    prepared = _prepared_file(size_status=SizeStatus.SOFT_LIMIT, content=SOURCE_WITH_TWO_FUNCTIONS)

    dispatch(prepared, container)

    assert var_agent.execute_agent_calls == []
    assert len(var_agent.execute_agent_batch_calls) == 1
    chunks, file_path = var_agent.execute_agent_batch_calls[0]
    assert file_path == "f.py"
    assert chunks == ["def foo():\n    return 1", "def bar():\n    return 2"]


@DISPATCH_FUNCTIONS
def test_chunked_incidents_are_offset_to_file_absolute_positions(dispatch: DispatchFn, container: AgentsContainer) -> None:
    incident = Incident(priority=Priority.MEDIUM, line_position="1-1", description="d", advice="a")
    container.chunk_agents[1]._incidents = [incident]  # var_agent
    prepared = _prepared_file(size_status=SizeStatus.SOFT_LIMIT, content=SOURCE_WITH_TWO_FUNCTIONS)

    entries = dispatch(prepared, container)

    var_entry = next(entry for entry in entries if entry.code_key == CodeKey.VAR)
    assert [incident.line_position for incident in var_entry.incidents] == ["1-1", "5-5"]


@DISPATCH_FUNCTIONS
def test_chunked_rating_is_recomputed_from_merged_incidents(dispatch: DispatchFn, container: AgentsContainer) -> None:
    incident = Incident(priority=Priority.MEDIUM, line_position="1-1", description="d", advice="a")
    container.chunk_agents[1]._incidents = [incident]  # var_agent, rating 100 on each individual chunk call
    prepared = _prepared_file(size_status=SizeStatus.SOFT_LIMIT, content=SOURCE_WITH_TWO_FUNCTIONS)

    entries = dispatch(prepared, container)

    var_entry = next(entry for entry in entries if entry.code_key == CodeKey.VAR)
    assert var_entry.rating == 100 - 7 - 7  # two chunks, one medium incident (-7) each


@DISPATCH_FUNCTIONS
def test_cmplx_gets_soft_limit_incident_appended_only_in_soft_limit_band(dispatch: DispatchFn, container: AgentsContainer) -> None:
    normal_entries = dispatch(_prepared_file(size_status=SizeStatus.NORMAL), container)
    soft_entries = dispatch(_prepared_file(size_status=SizeStatus.SOFT_LIMIT), container)

    normal_cmplx = next(entry for entry in normal_entries if entry.code_key == CodeKey.CMPLX)
    soft_cmplx = next(entry for entry in soft_entries if entry.code_key == CodeKey.CMPLX)
    assert normal_cmplx.incidents == []
    assert len(soft_cmplx.incidents) == 1
    assert "soft limit" in soft_cmplx.incidents[0].description


@DISPATCH_FUNCTIONS
def test_tcase_receives_paired_source_and_test_content_not_raw_code(
    dispatch: DispatchFn, container: AgentsContainer, tcase_agent: FakeAgent
) -> None:
    prepared = PreparedFile(
        source_file=SubmittedFile(file_path="f.py", content="def foo(): ..."),
        test_files=[SubmittedFile(file_path="test_f.py", content="def test_foo(): ...")],
        size_status=SizeStatus.NORMAL,
    )

    dispatch(prepared, container)

    content, file_path, _ = tcase_agent.execute_agent_calls[0]
    assert "def foo(): ..." in content
    assert "def test_foo(): ..." in content
    assert file_path == "f.py"


@DISPATCH_FUNCTIONS
def test_tcase_states_no_test_file_was_submitted_when_none_paired(
    dispatch: DispatchFn, container: AgentsContainer, tcase_agent: FakeAgent
) -> None:
    dispatch(_prepared_file(), container)

    content, _, _ = tcase_agent.execute_agent_calls[0]
    assert "No test file was submitted" in content


@DISPATCH_FUNCTIONS
def test_tcase_is_never_chunked_even_at_hard_limit(
    dispatch: DispatchFn, container: AgentsContainer, tcase_agent: FakeAgent
) -> None:
    prepared = _prepared_file(size_status=SizeStatus.HARD_LIMIT_EXCEEDED, content=SOURCE_WITH_TWO_FUNCTIONS)

    dispatch(prepared, container)

    assert len(tcase_agent.execute_agent_calls) == 1
    assert tcase_agent.execute_agent_batch_calls == []


@DISPATCH_FUNCTIONS
def test_dry_short_circuits_with_no_evidence(
    dispatch: DispatchFn, container: AgentsContainer, dry_judge: FakeDryJudge
) -> None:
    """Verify DRY skips the LLM call entirely when there's nothing to report."""
    entries = dispatch(_prepared_file(), container)

    dry_entry = next(entry for entry in entries if entry.code_key == CodeKey.DRY)
    assert dry_entry.rating == 100
    assert dry_entry.incidents == []
    assert dry_judge.judge_calls == []


@DISPATCH_FUNCTIONS
def test_dry_templates_intra_pr_evidence_with_no_judge_call(dispatch: DispatchFn, container: AgentsContainer, dry_judge: FakeDryJudge) -> None:
    """Verify a non-empty intra_pr_duplicates on the PreparedFile is
    reported directly — an exact structural-hash match needs no LLM judgment."""
    group = [
        LocatedChunk(StructuralMatch(file_path="f.py", chunk_name="foo", start_line=1, end_line=3), ADD_FUNCTION),
        LocatedChunk(StructuralMatch(file_path="other.py", chunk_name="bar", start_line=5, end_line=7), ADD_FUNCTION),
    ]
    prepared = _prepared_file(content=ADD_FUNCTION, intra_pr_duplicates=[group])

    entries = dispatch(prepared, container)

    dry_entry = next(entry for entry in entries if entry.code_key == CodeKey.DRY)
    assert len(dry_entry.incidents) == 1
    assert dry_entry.incidents[0].line_position == "1-3"
    assert "other.py:bar (lines 5-7)" in dry_entry.incidents[0].description
    assert dry_judge.judge_calls == []


@DISPATCH_FUNCTIONS
def test_dry_templates_cross_history_structural_evidence_with_no_judge_call(
    dispatch: DispatchFn,
    container: AgentsContainer,
    dry_judge: FakeDryJudge,
    structural_hash_store: StructuralHashStore,
) -> None:
    """Verify a repo-scoped review checks the indexed history and reports
    an exact structural match directly, without asking the judge."""
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    structural_hash_store.index_file(repo_data, "legacy/math_ops.py", ADD_FUNCTION)
    prepared = _prepared_file(content=ADD_FUNCTION, repo_data=repo_data)

    entries = dispatch(prepared, container)

    dry_entry = next(entry for entry in entries if entry.code_key == CodeKey.DRY)
    assert len(dry_entry.incidents) == 1
    assert "legacy/math_ops.py:add" in dry_entry.incidents[0].description
    assert dry_judge.judge_calls == []


@DISPATCH_FUNCTIONS
def test_dry_sends_a_semantic_match_to_the_judge(
    dispatch: DispatchFn,
    container: AgentsContainer,
    dry_judge: FakeDryJudge,
    rag_manager: FakeEmbeddingIndex,
) -> None:
    """Verify a fuzzy (semantic) cross-history candidate reaches the judge
    rather than being templated, and a confirmed verdict is offset to this
    file's own absolute line positions."""
    rag_manager._matches = [
        SimilarChunk(
            file_path="legacy/aggregates.py", chunk_name="total", start_line=1, end_line=2, text="t", score=0.9, code="def total(v): ..."
        )
    ]
    repo_data = RepoData(repo_id="repo-1", commit_sha="sha-1", owner_id="owner-1")
    dry_judge._incidents = [Incident(priority=Priority.MEDIUM, line_position="1-1", description="d", advice="a")]
    other_function = "def total(values):\n    total = 0\n    return total\n"
    prepared = _prepared_file(content=other_function, repo_data=repo_data)

    entries = dispatch(prepared, container)

    assert len(dry_judge.judge_calls) == 1
    dry_entry = next(entry for entry in entries if entry.code_key == CodeKey.DRY)
    assert dry_entry.incidents[0].line_position == "1-1"


@DISPATCH_FUNCTIONS
def test_dry_skips_cross_history_lookup_for_a_standalone_review(
    dispatch: DispatchFn, container: AgentsContainer, dry_judge: FakeDryJudge
) -> None:
    """Verify no repo_data means no history lookup is even attempted — same
    fallback ARCH/COUP's evidence hop already uses."""
    prepared = _prepared_file(content=ADD_FUNCTION, repo_data=None)

    entries = dispatch(prepared, container)

    dry_entry = next(entry for entry in entries if entry.code_key == CodeKey.DRY)
    assert dry_entry.rating == 100
    assert dry_judge.judge_calls == []


def _comparable(entries: list[AgentReviewEntry]) -> list[tuple]:
    """Reduces entries to (code_key, rating, incident positions) tuples,
    sorted by code_key, so two dispatch strategies' outputs can be
    compared regardless of branch execution order."""
    signatures = [
        (entry.code_key, entry.rating, [incident.line_position for incident in entry.incidents]) for entry in entries
    ]
    return sorted(signatures, key=lambda signature: signature[0].value)


@pytest.mark.asyncio
async def test_review_file_and_review_file_runnable_produce_equivalent_results(container: AgentsContainer) -> None:
    incident = Incident(priority=Priority.HIGH, line_position="1-1", description="d", advice="a")
    container.chunk_agents[1]._incidents = [incident]  # var_agent
    prepared = _prepared_file(size_status=SizeStatus.SOFT_LIMIT, content=SOURCE_WITH_TWO_FUNCTIONS)

    sequential = review_file(prepared, container)
    parallel = await review_file_runnable(prepared, container)

    assert _comparable(sequential) == _comparable(parallel)


@pytest.mark.asyncio
async def test_on_agent_reviewed_fires_once_per_branch(container: AgentsContainer) -> None:
    prepared = _prepared_file(size_status=SizeStatus.NORMAL, content=SOURCE_WITH_TWO_FUNCTIONS)
    reported: dict[CodeKey, AgentReviewEntry] = {}

    async def on_agent_reviewed(code_key: CodeKey, entry: AgentReviewEntry) -> None:
        reported[code_key] = entry

    entries = await review_file_runnable(prepared, container, on_agent_reviewed=on_agent_reviewed)

    assert set(reported.keys()) == {entry.code_key for entry in entries}
    for entry in entries:
        assert reported[entry.code_key] == entry
