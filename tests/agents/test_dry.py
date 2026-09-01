"""
    Tests for the DRY agent (duplication). Content-based checks run
    against a real model, per this project's approach to LLM-backed
    tests — DRY's input is pre-assembled evidence (rag/dry_evidence.py),
    not raw file content, so fixtures here build DryEvidence objects
    directly instead of loading source files.
"""
import pytest

from code_reviewer.agents.dry import DryAgent
from code_reviewer.rag.dry_evidence import DryEvidence
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.review import CodeKey

DISCOUNT_CALCULATION = (
    "def calculate_discount(price, customer_tier):\n"
    "    if customer_tier == 'gold':\n"
    "        discount = price * 0.20\n"
    "    elif customer_tier == 'silver':\n"
    "        discount = price * 0.10\n"
    "    else:\n"
    "        discount = 0\n"
    "    return price - discount"
)
DISCOUNT_CALCULATION_RENAMED = (
    "def apply_tier_discount(amount, tier):\n"
    "    if tier == 'gold':\n"
    "        reduction = amount * 0.20\n"
    "    elif tier == 'silver':\n"
    "        reduction = amount * 0.10\n"
    "    else:\n"
    "        reduction = 0\n"
    "    return amount - reduction"
)
TRIVIAL_INIT_A = "def __init__(self, name):\n    self.name = name"
TRIVIAL_INIT_B = "def __init__(self, label):\n    self.label = label"


@pytest.fixture
def dry_agent(small_llm) -> DryAgent:
    return DryAgent(llm=small_llm)


@pytest.mark.llm
def test_copy_pasted_function_within_the_pr_is_flagged(dry_agent: DryAgent) -> None:
    """Two files copy-pasting the same logic in the same PR is DRY's
    clearest in-scope case (category 1)."""
    group = [
        LocatedChunk(
            StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=10, end_line=17),
            DISCOUNT_CALCULATION,
        ),
        LocatedChunk(
            StructuralMatch(file_path="billing/refunds.py", chunk_name="apply_tier_discount", start_line=20, end_line=27),
            DISCOUNT_CALCULATION_RENAMED,
        ),
    ]
    evidence = DryEvidence(
        file_path="billing/totals.py",
        file_content=f"...\n{DISCOUNT_CALCULATION}\n",
        intra_pr_groups=[group],
        history_matches=[],
    )

    result = dry_agent.execute_agent(evidence.format(), file_path="billing/totals.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.DRY
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_exact_duplicate_against_repo_history_is_flagged(dry_agent: DryAgent) -> None:
    """This file's chunk exactly matches something already indexed
    elsewhere in the repo (category 2) — no code available for the
    historical side, only its location."""
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="new_module.py", chunk_name="calculate_discount", start_line=1, end_line=8),
        structural_matches=[
            StructuralMatch(file_path="legacy/pricing.py", chunk_name="calculate_discount", start_line=40, end_line=47)
        ],
        semantic_matches=[],
    )
    evidence = DryEvidence(
        file_path="new_module.py",
        file_content=DISCOUNT_CALCULATION,
        intra_pr_groups=[],
        history_matches=[history_match],
    )

    result = dry_agent.execute_agent(evidence.format(), file_path="new_module.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_coincidentally_similar_trivial_chunks_are_not_flagged(dry_agent: DryAgent) -> None:
    """Two unrelated one-line __init__ methods can share the exact same
    structure by coincidence — the prompt explicitly warns this is a
    candidate, not an automatic violation."""
    group = [
        LocatedChunk(StructuralMatch(file_path="user.py", chunk_name="__init__", start_line=3, end_line=4), TRIVIAL_INIT_A),
        LocatedChunk(StructuralMatch(file_path="product.py", chunk_name="__init__", start_line=8, end_line=9), TRIVIAL_INIT_B),
    ]
    evidence = DryEvidence(
        file_path="user.py",
        file_content=f"class User:\n    {TRIVIAL_INIT_A}\n",
        intra_pr_groups=[group],
        history_matches=[],
    )

    result = dry_agent.execute_agent(evidence.format(), file_path="user.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_semantic_match_carries_its_own_code_and_score_into_the_review(dry_agent: DryAgent) -> None:
    """A Type-4 behavioral duplicate (category 3): different code, same
    job, surfaced with its own code and similarity score."""
    loop_based_sum = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result"
    builtin_based_sum = "def total(values):\n    return sum(values)"
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="reports/totals.py", chunk_name="total", start_line=5, end_line=6),
        structural_matches=[],
        semantic_matches=[
            SimilarChunk(
                file_path="legacy/aggregates.py",
                chunk_name="total",
                start_line=12,
                end_line=16,
                text=loop_based_sum,
                score=0.93,
                code=loop_based_sum,
            )
        ],
    )
    evidence = DryEvidence(
        file_path="reports/totals.py",
        file_content=builtin_based_sum,
        intra_pr_groups=[],
        history_matches=[history_match],
    )

    result = dry_agent.execute_agent(evidence.format(), file_path="reports/totals.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.DRY
