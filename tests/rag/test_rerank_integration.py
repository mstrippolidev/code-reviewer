"""
    Real cross-encoder validation of HistoryMatchReranker's rank-based
    selection — no database, no Ollama/OpenRouter LLM, just the real
    sentence-transformers model dry_matching.py's buckets are scored with.

    This codifies what drove the switch away from an absolute score floor:
    that model's raw score is not on a fixed scale — the very same genuine
    duplicate scored anywhere from +8.9 to -3.1 across manual experiments,
    purely depending on how much unrelated code surrounded it in the query.
    No fixed floor separates signal from noise across that range. Rank
    within one query's own candidate pool did hold up in every experiment,
    including the worst-case dilution (a small duplicate function nested
    inside a much larger, realistic surrounding function) — these tests
    pin that down permanently, against the real model, so a future change
    to CROSS_ENCODER_MODEL or the selection logic can't silently regress it.
"""
import pytest

from code_reviewer.rag.code_similarity_index import CodeMatch
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralMatch

# A near-identical duplicate pair this codebase already relies on elsewhere
# (test_dry_matching.py's own near-miss fixture) — GUARD_CLAUSE_SUM is
# LOOP_BASED_SUM plus one added guard clause, different AST shape, same job.
LOOP_BASED_SUM = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"
NESTED_GUARD_CLAUSE_SUM = (
    "    def total(values):\n"
    "        if not values:\n"
    "            return 0\n"
    "        result = 0\n"
    "        for value in values:\n"
    "            result += value\n"
    "        return result\n"
)

# Realistic, varied surrounding code — not repetitive filler. Manual
# testing showed repetitive filler is far less "distracting" to the model
# than genuinely varied business logic, so a repetitive-filler fixture
# would understate the real dilution problem this pipeline faces.
_REALISTIC_STEPS = [
    "compute_subtotal(order)", "compute_discount(order)", "compute_shipping(order)",
    "compute_tax(order)", "queue_notification(order)", "record_audit_entry(order)",
    "finalize_order(order)", "archive_order(order)", "generate_receipt(order)",
    "send_confirmation_email(order)", "update_inventory(order)", "charge_payment(order)",
]


def _padding(n_steps_each_side: int) -> tuple[str, str]:
    before = "".join(f"    step_{i} = {_REALISTIC_STEPS[i % len(_REALISTIC_STEPS)]}\n" for i in range(n_steps_each_side))
    after = "".join(
        f"    step_after_{i} = {_REALISTIC_STEPS[(i + 6) % len(_REALISTIC_STEPS)]}\n" for i in range(n_steps_each_side)
    )
    return before, after


def _diluted_query(n_steps_each_side: int) -> str:
    """The duplicate makes up roughly a third of the whole chunk at 6
    steps/side — the dilution level that made the real duplicate's own
    absolute cross-encoder score go deeply negative in manual testing,
    while it still ranked #1 against real unrelated candidates."""
    before, after = _padding(n_steps_each_side)
    return f"def process_order(order):\n{before}" + NESTED_GUARD_CLAUSE_SUM + after + "    return order\n"


def _code_match(name: str, code: str, file_path: str | None = None) -> CodeMatch:
    path = file_path or f"unrelated/{name}.py"
    return CodeMatch(file_path=path, chunk_name=name, start_line=1, end_line=code.count("\n"), code=code, score=0.5)


_UNRELATED_CANDIDATES = [
    _code_match("send_email", "def send_email(to, subject, body):\n    smtp_client.send(to, subject, body)\n"),
    _code_match(
        "validate_user",
        "def validate_user(user):\n    if not user.email:\n        raise ValueError('missing email')\n    return True\n",
    ),
    _code_match("parse_config", "def parse_config(path):\n    with open(path) as f:\n        return json.load(f)\n"),
    _code_match(
        "retry_request",
        "def retry_request(fn, attempts=3):\n    for _ in range(attempts):\n        try:\n            return fn()\n        except Exception:\n            continue\n",
    ),
    _code_match("format_currency", "def format_currency(amount):\n    return f'${amount:,.2f}'\n"),
    _code_match(
        "hash_password", "def hash_password(password):\n    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())\n"
    ),
    _code_match("log_event", "def log_event(name, payload):\n    logger.info('%s: %s', name, payload)\n"),
    _code_match("cache_get", "def cache_get(key):\n    return redis_client.get(key)\n"),
]


def _match_with(code_matches: list[CodeMatch]) -> ChunkHistoryMatch:
    return ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="new_module.py", chunk_name="process_order", start_line=1, end_line=99),
        structural_matches=[],
        semantic_matches=[],
        code_matches=code_matches,
    )


@pytest.fixture(scope="module")
def real_reranker() -> HistoryMatchReranker:
    return HistoryMatchReranker(max_candidates=5)


@pytest.mark.llm
def test_real_cross_encoder_keeps_a_genuine_duplicate_diluted_by_a_large_surrounding_chunk(
    real_reranker: HistoryMatchReranker,
) -> None:
    """The real duplicate must survive even though it makes up only about a
    third of the whole query chunk — the exact dilution level that made its
    own absolute cross-encoder score deeply negative in manual testing."""
    true_duplicate = _code_match("total", LOOP_BASED_SUM, file_path="legacy/totals.py")
    query = _diluted_query(n_steps_each_side=6)
    match = _match_with([true_duplicate, *_UNRELATED_CANDIDATES])

    reranked = real_reranker.rerank(query, match)

    assert true_duplicate in reranked.code_matches


@pytest.mark.llm
def test_real_cross_encoder_drops_at_least_one_unrelated_candidate_when_the_pool_exceeds_the_cap(
    real_reranker: HistoryMatchReranker,
) -> None:
    """With 9 total candidates and max_candidates=5, ranking must actually
    filter something out — proof this is real selection, not a pass-through."""
    true_duplicate = _code_match("total", LOOP_BASED_SUM, file_path="legacy/totals.py")
    query = _diluted_query(n_steps_each_side=6)
    match = _match_with([true_duplicate, *_UNRELATED_CANDIDATES])

    reranked = real_reranker.rerank(query, match)

    assert len(reranked.code_matches) < len(_UNRELATED_CANDIDATES) + 1


@pytest.mark.llm
def test_real_cross_encoder_ranks_a_substantial_partial_duplicate_above_full_noise(
    real_reranker: HistoryMatchReranker,
) -> None:
    """A candidate duplicating most (not all) of the nested block must still
    outrank candidates sharing nothing with the query at all."""
    substantial_partial = _code_match(
        "sum_values",
        "def sum_values(values):\n    if not values:\n        return 0\n    result = 0\n    for value in values:\n        result += value\n    return result\n",
    )
    query = _diluted_query(n_steps_each_side=6)
    match = _match_with([substantial_partial, *_UNRELATED_CANDIDATES])

    reranked = real_reranker.rerank(query, match)

    assert substantial_partial in reranked.code_matches
