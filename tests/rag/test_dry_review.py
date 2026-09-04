"""
    Tests for build_dry_review_entry's own logic: which matches get
    templated versus sent to the judge, how a trivial hash match is
    excluded, how candidates are deduplicated before judging, and how the
    final rating is computed. The judge itself is faked so these exercise
    the merge/templating logic only, never a real LLM.
"""
from code_reviewer.rag.code_similarity_index import LexicalMatch
from code_reviewer.rag.dry_judge import JudgeCandidate
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.dry_review import build_dry_review_entry
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.review import CodeKey, Incident, Priority

DISCOUNT_CALCULATION = "def calculate_discount(price, tier):\n    if tier == 'gold':\n        return price * 0.8\n    return price"
TRIVIAL_INIT_A = "def __init__(self, name):\n    self.name = name"


class FakeDryJudge:
    def __init__(self, incidents: list[Incident] | None = None) -> None:
        self._incidents = incidents if incidents is not None else []
        self.judge_calls: list[tuple[str, list[JudgeCandidate]]] = []

    def judge(self, query_code: str, candidates: list[JudgeCandidate]) -> list[Incident]:
        self.judge_calls.append((query_code, candidates))
        return list(self._incidents)


def _incident(line_position: str = "1-1", priority: Priority = Priority.MEDIUM) -> Incident:
    return Incident(priority=priority, line_position=line_position, description="d", advice="a")


def _semantic_match(
    file_path: str = "legacy/aggregates.py", chunk_name: str = "total", start_line: int = 1, end_line: int = 5
) -> SimilarChunk:
    return SimilarChunk(
        file_path=file_path, chunk_name=chunk_name, start_line=start_line, end_line=end_line,
        text="t", score=0.9, code="def total(v): ...",
    )


def test_intra_pr_exact_match_is_templated_with_no_judge_call() -> None:
    group = [
        LocatedChunk(
            StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=10, end_line=13),
            DISCOUNT_CALCULATION,
        ),
        LocatedChunk(
            StructuralMatch(file_path="billing/refunds.py", chunk_name="apply_discount", start_line=20, end_line=23),
            DISCOUNT_CALCULATION,
        ),
    ]
    judge = FakeDryJudge()

    entry = build_dry_review_entry("billing/totals.py", DISCOUNT_CALCULATION, [group], [], judge)

    assert entry.code_key == CodeKey.DRY
    assert len(entry.incidents) == 1
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "10-13"
    assert "billing/refunds.py:apply_discount (lines 20-23)" in entry.incidents[0].description
    assert judge.judge_calls == []


def test_intra_pr_trivial_match_is_not_templated() -> None:
    group = [
        LocatedChunk(StructuralMatch(file_path="user.py", chunk_name="__init__", start_line=3, end_line=4), TRIVIAL_INIT_A),
        LocatedChunk(StructuralMatch(file_path="product.py", chunk_name="__init__", start_line=8, end_line=9), TRIVIAL_INIT_A),
    ]
    judge = FakeDryJudge()

    entry = build_dry_review_entry("user.py", f"class User:\n    {TRIVIAL_INIT_A}\n", [group], [], judge)

    assert entry.incidents == []
    assert entry.rating == 100


def test_intra_pr_only_reports_incidents_for_locations_in_this_file() -> None:
    group = [
        LocatedChunk(
            StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=10, end_line=13),
            DISCOUNT_CALCULATION,
        ),
        LocatedChunk(
            StructuralMatch(file_path="billing/refunds.py", chunk_name="apply_discount", start_line=20, end_line=23),
            DISCOUNT_CALCULATION,
        ),
    ]
    judge = FakeDryJudge()

    entry = build_dry_review_entry("billing/refunds.py", DISCOUNT_CALCULATION, [group], [], judge)

    assert len(entry.incidents) == 1
    assert entry.incidents[0].line_position == "20-23"


def test_cross_history_structural_match_is_templated() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="new_module.py", chunk_name="calculate_discount", start_line=1, end_line=4),
        structural_matches=[
            StructuralMatch(file_path="legacy/pricing.py", chunk_name="calculate_discount", start_line=40, end_line=43)
        ],
        semantic_matches=[],
    )
    judge = FakeDryJudge()

    entry = build_dry_review_entry("new_module.py", DISCOUNT_CALCULATION, [], [history_match], judge)

    assert len(entry.incidents) == 1
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-4"
    assert "legacy/pricing.py:calculate_discount (lines 40-43)" in entry.incidents[0].description
    assert judge.judge_calls == []


def test_cross_history_trivial_structural_match_is_not_templated() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="user.py", chunk_name="__init__", start_line=3, end_line=4),
        structural_matches=[StructuralMatch(file_path="product.py", chunk_name="__init__", start_line=8, end_line=9)],
        semantic_matches=[],
    )
    judge = FakeDryJudge()

    entry = build_dry_review_entry("user.py", f"class User:\n    {TRIVIAL_INIT_A}\n", [], [history_match], judge)

    assert entry.incidents == []


def test_fuzzy_candidates_reach_the_judge_and_are_offset_to_file_absolute() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="reports/totals.py", chunk_name="total", start_line=10, end_line=11),
        structural_matches=[],
        semantic_matches=[_semantic_match()],
    )
    judge = FakeDryJudge(incidents=[_incident(line_position="1-1")])
    file_content = "x = 0\n" * 9 + "def total(values):\n    return sum(values)\n"

    entry = build_dry_review_entry("reports/totals.py", file_content, [], [history_match], judge)

    assert len(judge.judge_calls) == 1
    assert entry.incidents[0].line_position == "10-10"


def test_fuzzy_candidates_are_deduplicated_by_location_across_buckets() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="reports/totals.py", chunk_name="total", start_line=1, end_line=2),
        structural_matches=[],
        semantic_matches=[_semantic_match()],
        lexical_matches=[
            LexicalMatch(file_path="legacy/aggregates.py", chunk_name="total", start_line=1, end_line=5, code="def total(v): ...", score=4.2)
        ],
    )
    judge = FakeDryJudge()

    build_dry_review_entry("reports/totals.py", "def total(values):\n    return sum(values)\n", [], [history_match], judge)

    assert len(judge.judge_calls[0][1]) == 1


def test_no_fuzzy_candidates_skips_the_judge_call() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="reports/totals.py", chunk_name="total", start_line=1, end_line=2),
        structural_matches=[],
        semantic_matches=[],
    )
    judge = FakeDryJudge()

    entry = build_dry_review_entry("reports/totals.py", "def total(values):\n    return sum(values)\n", [], [history_match], judge)

    assert judge.judge_calls == []
    assert entry.incidents == []


def test_rating_reflects_every_incident_source_combined() -> None:
    group = [
        LocatedChunk(
            StructuralMatch(file_path="billing/totals.py", chunk_name="calculate_discount", start_line=10, end_line=13),
            DISCOUNT_CALCULATION,
        ),
        LocatedChunk(
            StructuralMatch(file_path="billing/refunds.py", chunk_name="apply_discount", start_line=20, end_line=23),
            DISCOUNT_CALCULATION,
        ),
    ]
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="billing/totals.py", chunk_name="other", start_line=30, end_line=31),
        structural_matches=[],
        semantic_matches=[_semantic_match(file_path="x.py", chunk_name="other")],
    )
    judge = FakeDryJudge(incidents=[_incident(line_position="1-1", priority=Priority.LOW)])

    entry = build_dry_review_entry("billing/totals.py", DISCOUNT_CALCULATION, [group], [history_match], judge)

    assert entry.rating == 100 - 15 - 3  # one templated HIGH (-15) + one judged LOW (-3)
