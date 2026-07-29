"""
    Shared test helpers for loading fixture files.
"""
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(relative_path: str) -> str:
    """Reads a fixture file's content, e.g. load_fixture("naming/bad_abbreviations.py")."""
    return (FIXTURES_DIR / relative_path).read_text()
