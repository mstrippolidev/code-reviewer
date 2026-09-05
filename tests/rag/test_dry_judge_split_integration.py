"""
    Real end-to-end validation of 10.18.4's oversized-pair splitting: a
    near-identical function indexed for real into the test Postgres schema,
    found as a genuine fuzzy candidate by CrossHistoryDuplicateFinder's
    code-embedding bucket, surviving the real (rank-based) cross-encoder
    re-ranker, and finally confirmed by SizeGuardedDryJudge wrapping a real
    DryJudge — the query chunk it judges is deliberately oversized so the
    split path actually runs. Nothing here is mocked or faked.

    The fixture mirrors what made the switch from an absolute rerank floor
    to rank-based selection necessary in the first place: the duplicate is
    nested a few lines deep inside a much larger, realistically varied
    surrounding function, diluting its own absolute cross-encoder score
    (see test_rerank_integration.py) even though it still ranks at the top
    of its own candidate pool.
"""
from typing import Iterator

import pytest
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.postgres import PGVectorStore
from sqlalchemy import create_engine

from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.code_similarity_index import CodeMatch, CodeSimilarityIndex
from code_reviewer.rag.dry_judge import DryJudge, JudgeCandidate, format_location
from code_reviewer.rag.dry_judge_split import SizeGuardedDryJudge, SplitConfig
from code_reviewer.rag.dry_matching import CrossHistoryDuplicateFinder, DuplicateEvidenceSources
from code_reviewer.rag.embedding.ollama_code import OllamaCodeEmbeddingProvider
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.rag.vector_store import create_vector_store_instance
from code_reviewer.schemas.review import Incident

INTEGRATION_TEST_SCHEMA = "code_reviewer_test"
INTEGRATION_TEST_REPO_ID = "dry-judge-split-integration-test-repo"

# LOOP_BASED_SUM / a guard-clause variant of it is this codebase's own
# established near-miss pair (see test_dry_matching.py) — different AST
# shape (no structural-hash collision), same job, so it must reach the
# fuzzy code-embedding bucket and the judge rather than being templated.
LOOP_BASED_SUM = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"

_NESTED_GUARD_CLAUSE_SUM = (
    "    def total(values):\n"
    "        if not values:\n"
    "            return 0\n"
    "        result = 0\n"
    "        for value in values:\n"
    "            result += value\n"
    "        return result\n"
)

# Realistic, varied surrounding code, not repetitive filler — manual
# calibration showed repetitive filler is far less "distracting" to the
# cross-encoder than genuinely varied business logic, so it would
# understate how diluted a real buried duplicate's score actually gets.
_REALISTIC_STEPS = [
    "compute_subtotal(order)", "compute_discount(order)", "compute_shipping(order)",
    "compute_tax(order)", "queue_notification(order)", "record_audit_entry(order)",
    "finalize_order(order)", "archive_order(order)", "generate_receipt(order)",
    "send_confirmation_email(order)", "update_inventory(order)", "charge_payment(order)",
]
_before_steps = "".join(f"    step_{i} = {_REALISTIC_STEPS[i % len(_REALISTIC_STEPS)]}\n" for i in range(6))
_after_steps = "".join(f"    step_after_{i} = {_REALISTIC_STEPS[(i + 6) % len(_REALISTIC_STEPS)]}\n" for i in range(6))
BIG_CHUNK_WITH_NESTED_DUPLICATE = (
    f"def process_order(order):\n{_before_steps}" + _NESTED_GUARD_CLAUSE_SUM + _after_steps + "    return order\n"
)
_NESTED_DUPLICATE_START_LINE = BIG_CHUNK_WITH_NESTED_DUPLICATE.count("\n", 0, BIG_CHUNK_WITH_NESTED_DUPLICATE.index("def total")) + 1
_NESTED_DUPLICATE_END_LINE = _NESTED_DUPLICATE_START_LINE + _NESTED_GUARD_CLAUSE_SUM.count("\n") - 1

_SPLIT_CONFIG = SplitConfig(max_pair_chars=400, overlap_chars=80)


class _NoSemanticMatches:
    """Stands in for the semantic (explanation-embedding) bucket: this test
    exercises the code-embedding bucket specifically, matching this exact
    near-miss pair's own established bucket in test_dry_matching.py, so the
    semantic bucket is deliberately left with nothing indexed."""

    def find_similar(self, repo_data: RepoData, code: str, top_k: int = 5) -> list:
        return []


@pytest.fixture(scope="module")
def integration_repo_data() -> RepoData:
    return RepoData(repo_id=INTEGRATION_TEST_REPO_ID, commit_sha="abc123", owner_id="owner-1")


@pytest.fixture(scope="module")
def integration_structural_store() -> StructuralHashStore:
    """A real StructuralHashStore with nothing indexed into it — the nested
    duplicate's added guard clause gives it a different AST shape from
    LOOP_BASED_SUM on purpose, so it must reach the judge through the
    code-embedding bucket, never the structural one."""
    engine = create_engine("sqlite:///:memory:")
    return StructuralHashStore(engine=engine, schema_name=None)


@pytest.fixture(scope="module")
def integration_code_vector_store() -> Iterator[PGVectorStore]:
    """Real PGVectorStore pointed at the isolated test schema, never the
    production code_reviewer schema."""
    vector_store = create_vector_store_instance(schema_name=INTEGRATION_TEST_SCHEMA, table_name="code_raw_embeddings")

    yield vector_store

    vector_store.delete_nodes(
        filters=MetadataFilters(filters=[MetadataFilter(key="repo_id", value=INTEGRATION_TEST_REPO_ID)])
    )
    vector_store.client.dispose()


@pytest.fixture(scope="module")
def integration_code_similarity_index(integration_code_vector_store: PGVectorStore) -> CodeSimilarityIndex:
    return CodeSimilarityIndex(vector_store=integration_code_vector_store, embedding=OllamaCodeEmbeddingProvider())


@pytest.fixture(scope="module")
def integration_reranker() -> HistoryMatchReranker:
    """The real cross-encoder, at the same provisional max_candidates
    production is configured with."""
    return HistoryMatchReranker(max_candidates=get_settings().dry_rerank_max_candidates)


@pytest.fixture(scope="module")
def seeded_history(integration_code_similarity_index: CodeSimilarityIndex, integration_repo_data: RepoData) -> None:
    """Indexes LOOP_BASED_SUM once for the whole module — every test below
    only queries against it. No LLM call happens here: the code-embedding
    bucket embeds raw code directly, no explainer involved."""
    integration_code_similarity_index.index_file(integration_repo_data, "legacy/totals.py", LOOP_BASED_SUM)


@pytest.fixture
def integration_finder(
    integration_structural_store: StructuralHashStore,
    integration_code_similarity_index: CodeSimilarityIndex,
    integration_repo_data: RepoData,
    seeded_history: None,
) -> CrossHistoryDuplicateFinder:
    sources = DuplicateEvidenceSources(
        structural_hash_store=integration_structural_store,
        embedding_index=_NoSemanticMatches(),
        code_similarity_index=integration_code_similarity_index,
    )
    return CrossHistoryDuplicateFinder(sources, integration_repo_data)


@pytest.fixture(scope="module")
def size_guarded_judge(small_llm: LLMInterface) -> SizeGuardedDryJudge:
    """max_pair_chars=400 is well under BIG_CHUNK_WITH_NESTED_DUPLICATE's
    ~700 characters, so judging it for real always exercises the split
    path, never the plain batched call."""
    return SizeGuardedDryJudge(DryJudge(llm=small_llm), _SPLIT_CONFIG)


@pytest.fixture
def duplicate_candidates(
    integration_finder: CrossHistoryDuplicateFinder, integration_reranker: HistoryMatchReranker
) -> list[JudgeCandidate]:
    history_matches = integration_finder.find("new_module.py", BIG_CHUNK_WITH_NESTED_DUPLICATE)
    match = next(match for match in history_matches if match.chunk.chunk_name == "process_order")
    reranked = integration_reranker.rerank(BIG_CHUNK_WITH_NESTED_DUPLICATE, match)
    return [JudgeCandidate(location=format_location(candidate), code=candidate.code) for candidate in reranked.code_matches]


@pytest.mark.db
@pytest.mark.llm
def test_real_retrieval_finds_the_nested_duplicate_as_a_fuzzy_candidate(duplicate_candidates: list[JudgeCandidate]) -> None:
    """Before any judging happens: the code-embedding bucket must surface
    the indexed function as a candidate for the outer chunk that nests its
    near-identical duplicate, and that candidate must survive the real,
    rank-based cross-encoder selection despite being diluted by realistic
    surrounding code."""
    assert duplicate_candidates != []


@pytest.mark.db
@pytest.mark.llm
def test_nested_duplicate_inside_an_oversized_chunk_is_confirmed_after_splitting(
    duplicate_candidates: list[JudgeCandidate], size_guarded_judge: SizeGuardedDryJudge
) -> None:
    """The real judge, seeing only a split half of the oversized chunk at a
    time, must still confirm the nested duplicate — this is the whole
    reason 10.18.4 exists."""
    incidents = size_guarded_judge.judge(BIG_CHUNK_WITH_NESTED_DUPLICATE, duplicate_candidates)

    assert incidents != []


@pytest.mark.db
@pytest.mark.llm
def test_confirmed_duplicate_line_position_points_inside_the_nested_function(
    duplicate_candidates: list[JudgeCandidate], size_guarded_judge: SizeGuardedDryJudge
) -> None:
    """The reported range must overlap the nested duplicate block in the
    original, unsplit chunk — proof the split-piece offset lands back in
    the right place, not some split-boundary artifact."""
    incidents = size_guarded_judge.judge(BIG_CHUNK_WITH_NESTED_DUPLICATE, duplicate_candidates)
    start, end = _parse_line_range(incidents[0])

    assert start <= _NESTED_DUPLICATE_END_LINE and end >= _NESTED_DUPLICATE_START_LINE


def _parse_line_range(incident: Incident) -> tuple[int, int]:
    start_text, end_text = incident.line_position.split("-")
    return int(start_text), int(end_text)
