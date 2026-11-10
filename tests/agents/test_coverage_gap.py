"""
    Tests for the TCASE agent (test gap detection), run against a real
    small local model rather than a mock, per this project's approach to
    LLM-backed tests. What each source and test pair should produce lives in
    tests/fixtures/tcase/labels.json.
"""
import pytest

from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.schemas.paired import Pairing, build_standalone_test_file_content
from code_reviewer.schemas.submission import SubmittedFile
from evaluation.incidents import highest_priority
from evaluation.labels import FixtureLabel, load_labels
from evaluation.reviewer import pairing_of
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm

LABELS = load_labels("tcase")


@pytest.fixture
def test_gap_agent(small_llm: LLMInterface) -> CoverageGapAgent:
    return CoverageGapAgent(llm=small_llm)


def _pairing(source_name: str, test_name: str | None = None) -> Pairing:
    source_file = SubmittedFile(file_path=source_name, content=load_fixture(f"tcase/{source_name}"))
    test_files = []
    if test_name:
        test_files.append(
            SubmittedFile(file_path=test_name, content=load_fixture(f"tcase/{test_name}"))
        )
    return Pairing(source_file=source_file, test_files=test_files)


@pytest.mark.parametrize("label", LABELS, ids=lambda label: label.id)
def test_highest_priority_follows_the_label(test_gap_agent: CoverageGapAgent, label: FixtureLabel) -> None:
    """Verify the most severe incident TCASE reports is one the pair's label accepts.

    None means no incidents at all: a well-tested pair must not come back flagged.
    """
    entry = test_gap_agent.execute_agent(pairing_of(label).get_content(), file_path=label.path).review[0]

    assert highest_priority(entry) in label.accepted


def test_no_test_file_submitted_is_stated_explicitly(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("no_test_source.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert any(
        "test file" in incident.description.lower() and " no " in f" {incident.description.lower()} "
        for incident in entry.incidents
    )


def test_file_path_is_stamped_from_the_source_file(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("partially_tested_source.py", "partially_tested_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    assert all(entry.file_path == "partially_tested_source.py" for entry in result.review)


def _standalone_test_file_content(fixture_name: str) -> str:
    test_file = SubmittedFile(file_path=f"tests/{fixture_name}", content=load_fixture(f"tcase/{fixture_name}"))
    return build_standalone_test_file_content(test_file)


def test_standalone_well_designed_test_file_is_not_flagged(test_gap_agent: CoverageGapAgent) -> None:
    """Verify a well-designed test file reviewed on its own gets no incidents.

    With no source in scope, TCASE must not invent coverage gaps against
    code it can't see.
    """
    content = _standalone_test_file_content("standalone_well_designed_suite.py")

    result = test_gap_agent.execute_agent(content, file_path="tests/standalone_well_designed_suite.py")

    assert result.review[0].incidents == []


def test_standalone_poorly_designed_test_file_is_flagged(test_gap_agent: CoverageGapAgent) -> None:
    """Verify vacuous assertions, opaque names, and shared state in a lone test file are reported."""
    content = _standalone_test_file_content("standalone_poorly_designed_suite.py")

    result = test_gap_agent.execute_agent(content, file_path="tests/standalone_poorly_designed_suite.py")

    assert result.review[0].incidents != []


def test_standalone_test_file_review_never_claims_a_missing_test_file(test_gap_agent: CoverageGapAgent) -> None:
    """Verify the model takes the test-design branch, not the no-test-file-submitted branch.

    Stating that no test file was submitted would mean the model misread
    the test file under review as a source file with no tests.
    """
    content = _standalone_test_file_content("standalone_poorly_designed_suite.py")

    result = test_gap_agent.execute_agent(content, file_path="tests/standalone_poorly_designed_suite.py")

    descriptions = " ".join(incident.description.lower() for incident in result.review[0].incidents)
    assert "no test file" not in descriptions
