"""
    Normalizes a file path to the stem a source file and its test file share
    under the test_x.py / x_test.py naming convention.
"""
from pathlib import Path


def pairing_stem(file_path: str) -> str:
    stem = Path(file_path).stem.lower()
    if stem.startswith("test_"):
        return stem.removeprefix("test_")
    if stem.endswith("_test"):
        return stem.removesuffix("_test")
    return stem
