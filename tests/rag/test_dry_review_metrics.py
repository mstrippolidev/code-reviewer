"""
    Tests that DRY counts the exact duplicates it writes up without an LLM, by where they were found.
"""
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from code_reviewer.rag import dry_review
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.dry_review import build_dry_review_entry
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.telemetry.rag_metrics import RagMetrics
from tests.metric_points import RAG_DRY_EXACT_MATCHES, point_with
from tests.rag.test_dry_review import DISCOUNT_CALCULATION, FakeDryJudge

_ORIGIN = "code_reviewer.origin"


@pytest.fixture(autouse=True)
def route_metrics_to_the_test_provider(monkeypatch: pytest.MonkeyPatch, isolated_rag_metrics: RagMetrics) -> None:
    """Points DRY's review builder at a private provider, so assertions read only this test's recordings."""
    monkeypatch.setattr(dry_review, "rag_metrics", isolated_rag_metrics)


def _intra_pr_group() -> list[LocatedChunk]:
    return [
        LocatedChunk(
            StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=10, end_line=13),
            DISCOUNT_CALCULATION,
        ),
        LocatedChunk(
            StructuralMatch(file_path="billing/refunds.py", chunk_name="apply_discount", start_line=20, end_line=23),
            DISCOUNT_CALCULATION,
        ),
    ]


def _history_exact_match() -> ChunkHistoryMatch:
    return ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=1, end_line=4),
        structural_matches=[
            StructuralMatch(file_path="legacy/pricing.py", chunk_name="calculate_discount", start_line=40, end_line=43)
        ],
        semantic_matches=[],
    )


def test_an_exact_match_inside_the_pr_is_counted_as_intra_pr(metric_reader: InMemoryMetricReader) -> None:
    """Verify a templated duplicate between two files of the same PR counts under its own origin."""
    build_dry_review_entry("billing/totals.py", DISCOUNT_CALCULATION, [_intra_pr_group()], [], FakeDryJudge())

    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "intra_pr"}).value == 1
    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "history"}).value == 0


def test_an_exact_match_in_the_repo_history_is_counted_as_history(metric_reader: InMemoryMetricReader) -> None:
    """Verify a templated duplicate of already-indexed code counts under its own origin."""
    build_dry_review_entry("billing/totals.py", DISCOUNT_CALCULATION, [], [_history_exact_match()], FakeDryJudge())

    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "history"}).value == 1
    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "intra_pr"}).value == 0


def test_a_file_with_no_exact_matches_counts_zero_of_each(metric_reader: InMemoryMetricReader) -> None:
    """Verify a clean file reports zero for both origins, so a rate has a denominator."""
    build_dry_review_entry("billing/totals.py", DISCOUNT_CALCULATION, [], [], FakeDryJudge())

    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "history"}).value == 0
    assert point_with(metric_reader, RAG_DRY_EXACT_MATCHES, {_ORIGIN: "intra_pr"}).value == 0
