"""
    Tests for dry_evidence: attaching code to bare duplicate locations,
    narrowing groups to one file, and formatting the final evidence report
    DRY's LLM reads. Pure data transforms — no LLM, no database.
"""
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_evidence import DryEvidence, attach_code, groups_for_file
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile

ADD_FUNCTION = "x = 0\ndef add(a, b):\n    return a + b\n"


def test_attach_code_pairs_a_match_with_its_own_file_code() -> None:
    files = [SubmittedFile(file_path="a.py", content=ADD_FUNCTION)]
    groups = [[StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3)]]

    located_groups = attach_code(files, groups)

    assert located_groups[0][0].code == "def add(a, b):\n    return a + b"


def test_attach_code_reads_each_match_from_its_own_file() -> None:
    files = [
        SubmittedFile(file_path="a.py", content="def foo():\n    return 1\n"),
        SubmittedFile(file_path="b.py", content="def bar():\n    return 2\n"),
    ]
    groups = [
        [
            StructuralMatch(file_path="a.py", chunk_name="foo", start_line=1, end_line=2),
            StructuralMatch(file_path="b.py", chunk_name="bar", start_line=1, end_line=2),
        ]
    ]

    located_groups = attach_code(files, groups)

    codes = {located.match.file_path: located.code for located in located_groups[0]}
    assert codes == {"a.py": "def foo():\n    return 1", "b.py": "def bar():\n    return 2"}


def test_attach_code_defaults_to_empty_string_for_an_unknown_file() -> None:
    groups = [[StructuralMatch(file_path="missing.py", chunk_name="foo", start_line=1, end_line=2)]]

    located_groups = attach_code([], groups)

    assert located_groups[0][0].code == ""


def test_attach_code_preserves_group_structure() -> None:
    files = [SubmittedFile(file_path="a.py", content=ADD_FUNCTION)]
    groups = [
        [StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3)],
        [StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3)],
    ]

    located_groups = attach_code(files, groups)

    assert len(located_groups) == 2


def test_groups_for_file_keeps_only_groups_touching_that_file() -> None:
    located_a = LocatedChunk(StructuralMatch(file_path="a.py", chunk_name="foo", start_line=1, end_line=2), "code")
    located_b = LocatedChunk(StructuralMatch(file_path="b.py", chunk_name="bar", start_line=1, end_line=2), "code")
    located_c = LocatedChunk(StructuralMatch(file_path="c.py", chunk_name="baz", start_line=1, end_line=2), "code")
    groups = [[located_a, located_b], [located_c]]

    result = groups_for_file(groups, "a.py")

    assert result == [[located_a, located_b]]


def test_groups_for_file_returns_nothing_when_no_group_touches_it() -> None:
    located_a = LocatedChunk(StructuralMatch(file_path="a.py", chunk_name="foo", start_line=1, end_line=2), "code")

    result = groups_for_file([[located_a]], "z.py")

    assert result == []


def test_has_matches_is_false_with_no_evidence_at_all() -> None:
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[], history_matches=[])

    assert evidence.has_matches() is False


def test_has_matches_is_true_with_only_intra_pr_evidence() -> None:
    located = LocatedChunk(StructuralMatch(file_path="a.py", chunk_name="foo", start_line=1, end_line=2), "code")
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[[located]], history_matches=[])

    assert evidence.has_matches() is True


def test_has_matches_is_true_with_only_history_evidence() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="foo", start_line=1, end_line=2),
        structural_matches=[],
        semantic_matches=[],
    )
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[], history_matches=[history_match])

    assert evidence.has_matches() is True


def test_format_always_names_the_file_under_review() -> None:
    evidence = DryEvidence(file_path="billing/totals.py", file_content="", intra_pr_groups=[], history_matches=[])

    assert "billing/totals.py" in evidence.format()


def test_format_omits_intra_pr_section_when_there_are_no_groups() -> None:
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[], history_matches=[])

    assert "DUPLICATE GROUPS WITHIN THIS PR" not in evidence.format()


def test_format_includes_intra_pr_group_locations_and_code() -> None:
    located = LocatedChunk(StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3), "def add(a, b):\n    return a + b")
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[[located]], history_matches=[])

    report = evidence.format()

    assert "DUPLICATE GROUPS WITHIN THIS PR" in report
    assert "a.py:add (lines 2-3)" in report
    assert "def add(a, b):\n    return a + b" in report


def test_format_omits_history_section_when_there_are_no_matches() -> None:
    evidence = DryEvidence(file_path="a.py", file_content="", intra_pr_groups=[], history_matches=[])

    assert "DUPLICATES AGAINST ALREADY-INDEXED REPO HISTORY" not in evidence.format()


def test_format_extracts_the_current_chunk_code_from_file_content() -> None:
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3),
        structural_matches=[],
        semantic_matches=[],
    )
    evidence = DryEvidence(file_path="a.py", file_content=ADD_FUNCTION, intra_pr_groups=[], history_matches=[history_match])

    report = evidence.format()

    assert "def add(a, b):\n    return a + b" in report


def test_format_shows_structural_matches_as_location_only_no_code() -> None:
    """Verify a structural match's other-side code block never appears —
    that side's code was never available to attach in the first place."""
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3),
        structural_matches=[StructuralMatch(file_path="legacy/math_ops.py", chunk_name="add", start_line=10, end_line=11)],
        semantic_matches=[],
    )
    evidence = DryEvidence(file_path="a.py", file_content=ADD_FUNCTION, intra_pr_groups=[], history_matches=[history_match])

    report = evidence.format()

    assert "Exact structural matches already indexed:" in report
    assert "legacy/math_ops.py:add (lines 10-11)" in report


def test_format_shows_semantic_matches_with_code_and_similarity_score() -> None:
    semantic_match = SimilarChunk(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, text="...", score=0.87, code="def total(v):\n    return sum(v)"
    )
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3),
        structural_matches=[],
        semantic_matches=[semantic_match],
    )
    evidence = DryEvidence(file_path="a.py", file_content=ADD_FUNCTION, intra_pr_groups=[], history_matches=[history_match])

    report = evidence.format()

    assert "Similar-behavior matches already indexed (not exact clones):" in report
    assert "legacy/totals.py:total (lines 1-3, similarity=0.87)" in report
    assert "def total(v):\n    return sum(v)" in report


def test_format_shows_code_matches_with_code_and_similarity_score() -> None:
    code_match = CodeMatch(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, code="def total(v):\n    return sum(v)", score=0.81
    )
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3),
        structural_matches=[],
        semantic_matches=[],
        code_matches=[code_match],
    )
    evidence = DryEvidence(file_path="a.py", file_content=ADD_FUNCTION, intra_pr_groups=[], history_matches=[history_match])

    report = evidence.format()

    assert "Similar raw-code matches already indexed (behaviorally uncertain):" in report
    assert "legacy/totals.py:total (lines 1-3, similarity=0.81)" in report
    assert "def total(v):\n    return sum(v)" in report


def test_format_shows_lexical_matches_with_code_and_bm25_score() -> None:
    lexical_match = LexicalMatch(
        file_path="legacy/totals.py", chunk_name="total", start_line=1, end_line=3, code="def total(v):\n    return sum(v)", score=4.62
    )
    history_match = ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="add", start_line=2, end_line=3),
        structural_matches=[],
        semantic_matches=[],
        lexical_matches=[lexical_match],
    )
    evidence = DryEvidence(file_path="a.py", file_content=ADD_FUNCTION, intra_pr_groups=[], history_matches=[history_match])

    report = evidence.format()

    assert "Matches sharing distinctive vocabulary already indexed (keyword overlap):" in report
    assert "legacy/totals.py:total (lines 1-3, bm25=4.62)" in report
    assert "def total(v):\n    return sum(v)" in report
