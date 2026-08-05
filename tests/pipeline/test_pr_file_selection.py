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
def test_test_files_are_set_aside_as_context_not_skipped(test_file_path: str) -> None:
    files = [_file(test_file_path), _file("a.py"), _file("b.py"), _file("c.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert test_file_path not in {file.file_path for file in selected}
    assert test_file_path not in {entry.file_path for entry in skipped}
    assert test_file_path in {file.file_path for file in test_files}


def test_test_files_are_set_aside_even_when_submission_is_under_cap() -> None:
    files = [_file("login.py"), _file("test_login.py")]

    selected, skipped, test_files = select_pr_files(files)

    assert selected == [files[0]]
    assert skipped == []
    assert test_files == [files[1]]


def test_test_files_never_count_against_the_cap() -> None:
    files = [
        _file("test_small.py"),
        _file("test_largest.py"),
        _file("small.py", line_count=10),
        _file("largest.py", line_count=300),
    ]

    selected, skipped, test_files = select_pr_files(files)

    selected_paths = {file.file_path for file in selected}
    assert selected_paths == {"small.py", "largest.py"}
    assert skipped == []
    assert {file.file_path for file in test_files} == {"test_small.py", "test_largest.py"}


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
