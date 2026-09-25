"""
    Pairs each source file with the test files that match it by naming
    convention (test_x.py / x_test.py), so TCASE can read both.
"""
from collections import Counter

from code_reviewer.pipeline.pairing_stem import pairing_stem
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.submission import SubmittedFile


def pair_source_files_with_tests(
    source_files: list[SubmittedFile], test_files: list[SubmittedFile]
) -> list[Pairing]:
    """Pairs every file in source_files with its matching files in test_files.

    A stem shared by more than one source file is ambiguous — pairing could
    attach a test file to the wrong source, which is worse than not pairing
    at all, so no test files are matched for any file sharing that stem.
    """
    stem_counts = Counter(pairing_stem(source.file_path) for source in source_files)

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
    stem = pairing_stem(source.file_path)
    if stem_counts[stem] > 1:
        return []
    return [test_file for test_file in test_files if pairing_stem(test_file.file_path) == stem]
