"""
    Label-driven tests for the agents that review one file on its own: each
    fixture in an agent's labels.json goes to a real model and the most
    severe incident must be one its label accepts. CMPLX has its own file
    (it needs call-depth reports) and TCASE too (it needs a test file).
"""
import pytest

from evaluation.incidents import highest_priority
from evaluation.labels import FixtureLabel, load_labels
from evaluation.reviewer import AGENT_CLASS_BY_FOLDER, COMPLEXITY_FOLDER, COVERAGE_GAP_FOLDER, LabelReviewer

pytestmark = pytest.mark.llm

SINGLE_FILE_FOLDERS = [
    folder for folder in AGENT_CLASS_BY_FOLDER if folder not in {COMPLEXITY_FOLDER, COVERAGE_GAP_FOLDER}
]

CASES = [
    pytest.param(folder, label, id=f"{folder}-{label.id}")
    for folder in SINGLE_FILE_FOLDERS
    for label in load_labels(folder)
]


@pytest.mark.parametrize("folder, label", CASES)
def test_highest_priority_follows_the_label(small_llm, folder: str, label: FixtureLabel) -> None:
    """Verify the most severe incident an agent reports is one the fixture's label accepts.

    None means no incidents at all: a clean file must not come back flagged.
    """
    entry = LabelReviewer(folder, small_llm).review(label)

    assert highest_priority(entry) in label.accepted
