"""
    PR-level file selection. When a submission exceeds the per-PR file cap,
    excludes non-logic files first, then ranks what remains by line count
    and keeps only the top N. Runs once per PR, before any per-file pipeline
    step (raw character guard, intake screen, file size guard, 14 agents).
"""
from pathlib import Path

from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import SkippedFile
from code_reviewer.schemas.submission import SubmittedFile

_MIGRATION_PATH_SEGMENTS = ("migrations/", "alembic/versions/")
_VENDORED_PATH_SEGMENTS = ("vendor/", "node_modules/", ".venv/", "venv/", "site-packages/")
_TEST_PATH_SEGMENTS = ("tests/", "test/")
_LOCK_FILE_NAMES = {
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "composer.lock",
}


def select_pr_files(files: list[SubmittedFile]) -> tuple[list[SubmittedFile], list[SkippedFile], list[SubmittedFile]]:
    """Returns the files to review, the files skipped (with a reason for each), and the test files set aside as TCASE context."""
    candidates, excluded, test_files = _partition_non_logic_files(files)

    max_files = get_settings().max_files_per_submission
    if len(candidates) <= max_files:
        return candidates, excluded, test_files

    ranked = sorted(candidates, key=lambda file: file.content.count("\n"), reverse=True)
    selected, cut = ranked[:max_files], ranked[max_files:]
    skipped_for_cap = [
        SkippedFile(file_path=file.file_path, reason="exceeded_pr_file_cap") for file in cut
    ]
    return selected, excluded + skipped_for_cap, test_files


def _partition_non_logic_files(
    files: list[SubmittedFile],
) -> tuple[list[SubmittedFile], list[SkippedFile], list[SubmittedFile]]:
    """Splits files into review candidates and non-logic files excluded outright."""
    candidates: list[SubmittedFile] = []
    excluded: list[SkippedFile] = []
    test_files: list[SubmittedFile] = []
    for file in files:
        reason = _non_logic_file_reason(file.file_path)
        if reason is None:
            candidates.append(file)
        elif reason == "test_file":
            test_files.append(file)
        else:
            excluded.append(SkippedFile(file_path=file.file_path, reason=reason))
    return candidates, excluded, test_files


def _non_logic_file_reason(file_path: str) -> str | None:
    """Names why file_path is out of scope for review, or None if it's a candidate."""
    if _is_migration_file(file_path):
        return "migration_file"
    if _is_lock_file(file_path):
        return "lock_file"
    if _is_vendored_file(file_path):
        return "vendored_file"
    if is_test_file(file_path):
        return "test_file"
    return None


def _is_migration_file(file_path: str) -> bool:
    return any(segment in file_path for segment in _MIGRATION_PATH_SEGMENTS)


def _is_lock_file(file_path: str) -> bool:
    return Path(file_path).name in _LOCK_FILE_NAMES


def _is_vendored_file(file_path: str) -> bool:
    return any(segment in file_path for segment in _VENDORED_PATH_SEGMENTS)


def is_test_file(file_path: str) -> bool:
    name = Path(file_path).name.lower()
    if any(segment in file_path.lower() for segment in _TEST_PATH_SEGMENTS):
        return True
    return name.startswith("test_") or name.endswith("_test.py")
