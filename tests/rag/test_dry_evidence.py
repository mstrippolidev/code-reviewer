"""
    Tests for dry_evidence: attaching code to bare duplicate locations and
    narrowing groups to one file. Pure data transforms — no LLM, no database.
"""
from code_reviewer.rag.dry_evidence import attach_code, groups_for_file
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
