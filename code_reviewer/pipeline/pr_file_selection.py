"""
    PR-level file selection. When a submission exceeds the per-PR file cap,
    excludes non-logic files first, then ranks what remains by line count
    and keeps only the top N. Runs once per PR, before any per-file pipeline
    step (raw character guard, intake screen, file size guard, 14 agents).
"""
from dataclasses import dataclass
from pathlib import Path

from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.pairing_stem import pairing_stem
from code_reviewer.schemas.review import SkippedFile
from code_reviewer.schemas.submission import SubmittedFile

_MIGRATION_PATH_SEGMENTS = ("migrations/", "alembic/versions/")
_VENDORED_PATH_SEGMENTS = ("vendor/", "node_modules/", ".venv/", "venv/", "site-packages/")
_TEST_PATH_SEGMENTS = ("tests/", "test/")
_TEST_FILE_REASON = "test_file_context_only"
_LOCK_FILE_NAMES = {
    "poetry.lock",
    "Pipfile.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "composer.lock",
}


@dataclass(frozen=True)
class _PartitionedFiles:
    source_candidates: list[SubmittedFile]
    standalone_test_files: list[SubmittedFile]
    paired_test_files: list[SubmittedFile]
    excluded: list[SkippedFile]


def select_pr_files(files: list[SubmittedFile]) -> tuple[list[SubmittedFile], list[SkippedFile], list[SubmittedFile]]:
    """Returns the files to review, the files skipped (with a reason for each), and the test files set aside as TCASE context.

    A test file with no source file in the submission to pair it to is
    reviewed as its own target, but source files always claim cap slots
    first — a standalone test file only fills a slot left over after them.
    """
    partitioned = _partition_files(files)
    max_files = get_settings().max_files_per_submission

    selected_sources, cut_sources = _rank_and_cap(partitioned.source_candidates, max_files)
    remaining_slots = max_files - len(selected_sources)
    selected_tests, cut_tests = _rank_and_cap(partitioned.standalone_test_files, remaining_slots)

    skipped_for_cap = [
        SkippedFile(file_path=file.file_path, reason="exceeded_pr_file_cap") for file in cut_sources + cut_tests
    ]
    return selected_sources + selected_tests, partitioned.excluded + skipped_for_cap, partitioned.paired_test_files


def _partition_files(files: list[SubmittedFile]) -> _PartitionedFiles:
    source_candidates: list[SubmittedFile] = []
    test_candidates: list[SubmittedFile] = []
    excluded: list[SkippedFile] = []
    for file in files:
        reason = _non_logic_file_reason(file.file_path)
        if reason is not None:
            excluded.append(SkippedFile(file_path=file.file_path, reason=reason))
        elif is_test_file(file.file_path):
            test_candidates.append(file)
        else:
            source_candidates.append(file)

    source_stems = {pairing_stem(file.file_path) for file in source_candidates}
    paired = [file for file in test_candidates if pairing_stem(file.file_path) in source_stems]
    standalone = [file for file in test_candidates if pairing_stem(file.file_path) not in source_stems]
    excluded += [SkippedFile(file_path=file.file_path, reason=_TEST_FILE_REASON) for file in paired]
    return _PartitionedFiles(source_candidates, standalone, paired, excluded)


def _rank_and_cap(files: list[SubmittedFile], cap: int) -> tuple[list[SubmittedFile], list[SubmittedFile]]:
    ranked = sorted(files, key=lambda file: file.content.count("\n"), reverse=True)
    return ranked[:cap], ranked[cap:]


def _non_logic_file_reason(file_path: str) -> str | None:
    """Names why file_path is out of scope for review, or None if it's a candidate."""
    if _is_migration_file(file_path):
        return "migration_file"
    if _is_lock_file(file_path):
        return "lock_file"
    if _is_vendored_file(file_path):
        return "vendored_file"
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
