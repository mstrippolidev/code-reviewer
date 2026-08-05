"""
    Pairs each source file with the test files that match it by naming
    convention (test_x.py / x_test.py), so TCASE can read both.
"""
from collections import Counter
from pathlib import Path

from code_reviewer.pipeline.pr_file_selection import is_test_file
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.submission import SubmittedFile


def pair_source_files_with_tests(files: list[SubmittedFile]) -> list[Pairing]:
    """Pairs every source file in files with its matching test files, if any.

    A stem shared by more than one source file is ambiguous — pairing could
    attach a test file to the wrong source, which is worse than not pairing
    at all, so no test files are matched for any file sharing that stem.
    """
    source_files = [file for file in files if not is_test_file(file.file_path)]
    test_files = [file for file in files if is_test_file(file.file_path)]
    stem_counts = Counter(_pairing_stem(source.file_path) for source in source_files)

    return [
        Pairing(
            source_file=source,
            test_files=_matching_test_files(source, test_files, stem_counts),
        )
        for source in source_files
    ]


def _matching_test_files(
    source: SubmittedFile, test_files: list[SubmittedFile], stem_counts: Counter
) -> list[SubmittedFile]:
    stem = _pairing_stem(source.file_path)
    if stem_counts[stem] > 1:
        return []
    return [test_file for test_file in test_files if _pairing_stem(test_file.file_path) == stem]


def _pairing_stem(file_path: str) -> str:
    """Normalizes a file's basename to its pairing stem, stripping the
    test_/_test naming convention so a source and its test compare equal."""
    stem = Path(file_path).stem.lower()
    if stem.startswith("test_"):
        return stem.removeprefix("test_")
    if stem.endswith("_test"):
        return stem.removesuffix("_test")
    return stem
