import pytest

from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.pr_file_selection import select_pr_files
from code_reviewer.schemas.submission import SubmittedFile


def _file(path: str, line_count: int = 1) -> SubmittedFile:
    return SubmittedFile(file_path=path, content="x\n" * line_count)


@pytest.fixture(autouse=True)
def small_file_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_files_per_submission", 2)


def test_under_cap_returns_all_files_with_no_skips() -> None:
    files = [_file("a.py"), _file("b.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert selected == files
    assert skipped == []
    assert test_files == []


def test_at_cap_boundary_returns_all_files_with_no_skips() -> None:
    files = [_file("a.py"), _file("b.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert len(selected) == 2
    assert skipped == []
    assert test_files == []


@pytest.mark.parametrize(
    "file_path,expected_reason",
    [
        ("app/migrations/0001_initial.py", "migration_file"),
        ("alembic/versions/abc123_add_column.py", "migration_file"),
        ("poetry.lock", "lock_file"),
        ("frontend/package-lock.json", "lock_file"),
        ("node_modules/left-pad/index.js", "vendored_file"),
        (".venv/lib/site.py", "vendored_file"),
    ],
)
def test_non_logic_files_are_excluded_with_correct_reason(
    file_path: str, expected_reason: str
) -> None:
    files = [_file(file_path), _file("a.py"), _file("b.py"), _file("c.py")]

    _, skipped, _ = select_pr_files(files)

    skipped_by_path = {entry.file_path: entry.reason for entry in skipped}
    assert skipped_by_path[file_path] == expected_reason


def test_non_logic_files_are_excluded_even_when_submission_is_under_cap() -> None:
    files = [_file("app/migrations/0001_initial.py"), _file("a.py")]

    selected, skipped, _ = select_pr_files(files)

    assert selected == [files[1]]
    skipped_by_path = {entry.file_path: entry.reason for entry in skipped}
    assert skipped_by_path == {"app/migrations/0001_initial.py": "migration_file"}


@pytest.mark.parametrize(
    "test_file_path",
    ["tests/test_service.py", "app/test_service.py", "app/service_test.py"],
)
def test_test_files_are_set_aside_as_context_and_reported(test_file_path: str) -> None:
    files = [_file(test_file_path), _file("app/service.py"), _file("b.py"), _file("c.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert test_file_path not in {file.file_path for file in selected}
    assert test_file_path in {file.file_path for file in test_files}
    skipped_by_path = {entry.file_path: entry.reason for entry in skipped}
    assert skipped_by_path[test_file_path] == "test_file_context_only"


def test_test_files_are_set_aside_even_when_submission_is_under_cap() -> None:
    files = [_file("login.py"), _file("test_login.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert selected == [files[0]]
    assert test_files == [files[1]]
    assert [entry.file_path for entry in skipped] == ["test_login.py"]


def test_paired_test_files_never_count_against_the_cap() -> None:
    files = [
        _file("test_small.py"),
        _file("test_largest.py"),
        _file("small.py", line_count=10),
        _file("largest.py", line_count=300),
    ]

    selected, skipped, test_files = select_pr_files(files)

    selected_paths = {file.file_path for file in selected}
    assert selected_paths == {"small.py", "largest.py"}
    assert {file.file_path for file in test_files} == {"test_small.py", "test_largest.py"}
    assert {entry.reason for entry in skipped} == {"test_file_context_only"}


def test_lone_test_file_with_no_source_partner_is_selected_for_review() -> None:
    """Verify a test file submitted without its source file becomes a review target.

    With no source file to pair it to, setting it aside as TCASE context
    would leave it reviewed by nobody.
    """
    files = [_file("tests/test_payment.py")]

    selected, _, _ = select_pr_files(files)

    assert selected == files


def test_lone_test_file_with_no_source_partner_is_not_reported_as_skipped() -> None:
    """Verify a promoted standalone test file carries no test_file_context_only skip."""
    files = [_file("tests/test_payment.py")]

    _, skipped, _ = select_pr_files(files)

    assert skipped == []


def test_lone_test_file_with_no_source_partner_is_not_used_as_tcase_context() -> None:
    """Verify a promoted standalone test file is not also returned as pairing context."""
    files = [_file("tests/test_payment.py"), _file("orders.py")]

    _, _, test_files = select_pr_files(files)

    assert test_files == []


def test_standalone_test_file_never_displaces_a_shorter_source_file_from_the_cap() -> None:
    """Verify source files claim cap slots before any standalone test file, regardless of length."""
    files = [
        _file("test_huge_suite.py", line_count=900),
        _file("small.py", line_count=5),
        _file("tiny.py", line_count=2),
    ]

    selected, _, _ = select_pr_files(files)

    assert {file.file_path for file in selected} == {"small.py", "tiny.py"}


def test_standalone_test_file_cut_by_the_cap_is_reported_as_exceeding_it() -> None:
    """Verify a standalone test file left without a slot is reported, not silently dropped."""
    files = [_file("test_huge_suite.py", line_count=900), _file("small.py"), _file("tiny.py")]

    _, skipped, _ = select_pr_files(files)

    assert {entry.file_path: entry.reason for entry in skipped} == {"test_huge_suite.py": "exceeded_pr_file_cap"}


def test_standalone_test_files_fill_leftover_slots_ranked_by_line_count() -> None:
    """Verify leftover cap slots go to the longest standalone test files first."""
    files = [
        _file("orders.py", line_count=50),
        _file("test_short.py", line_count=5),
        _file("test_long.py", line_count=200),
    ]

    selected, _, _ = select_pr_files(files)

    assert {file.file_path for file in selected} == {"orders.py", "test_long.py"}


def test_over_cap_keeps_top_n_candidates_by_line_count() -> None:
    files = [
        _file("small.py", line_count=10),
        _file("largest.py", line_count=300),
        _file("medium.py", line_count=100),
    ]

    selected, skipped, test_files = select_pr_files(files)

    selected_paths = {file.file_path for file in selected}
    assert selected_paths == {"largest.py", "medium.py"}
    assert [entry.file_path for entry in skipped] == ["small.py"]
    assert skipped[0].reason == "exceeded_pr_file_cap"
    assert test_files == []


def test_non_logic_exclusion_and_ranking_combine() -> None:
    files = [
        _file("app/migrations/0001_initial.py", line_count=500),
        _file("poetry.lock", line_count=500),
        _file("small.py", line_count=10),
        _file("largest.py", line_count=300),
        _file("medium.py", line_count=100),
    ]

    selected, skipped, test_files = select_pr_files(files)

    selected_paths = {file.file_path for file in selected}
    skipped_reasons = {entry.file_path: entry.reason for entry in skipped}

    assert selected_paths == {"largest.py", "medium.py"}
    assert skipped_reasons == {
        "app/migrations/0001_initial.py": "migration_file",
        "poetry.lock": "lock_file",
        "small.py": "exceeded_pr_file_cap",
    }
    assert test_files == []
