"""
    Tests for the TCASE agent (test gap detection), run against a real
    small local model rather than a mock, per this project's approach to
    LLM-backed tests.
"""
import pytest

from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.schemas.paired import Pairing, build_standalone_test_file_content
from code_reviewer.schemas.review import CodeKey, Priority
from code_reviewer.schemas.submission import SubmittedFile
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


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


def test_fully_tested_code_is_not_flagged(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("well_tested_source.py", "well_tested_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.code_key == CodeKey.TCASE
    assert entry.incidents == []
    assert entry.rating == 100


def test_parametrized_coverage_is_not_flagged_as_a_gap(test_gap_agent: CoverageGapAgent) -> None:
    """A single parametrized test exercising all three branches must not
    be mistaken for a gap just because there's only one test function —
    what matters is which paths the cases actually cover."""
    pairing = _pairing("parametrized_coverage_source.py", "parametrized_coverage_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_trivial_passthrough_with_no_test_file_is_not_flagged(test_gap_agent: CoverageGapAgent) -> None:
    """A bare constant has no testable behavior at all, so the prompt's
    own carve-out applies even though no test file was submitted."""
    pairing = _pairing("trivial_passthrough_source.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_mocked_away_logic_out_of_scope_is_flagged_low(test_gap_agent: CoverageGapAgent) -> None:
    """Generalization check, deliberately independent of the worked
    example now in TCASE's prompt (vacuous assertions): stubbing out the
    collaborator that does the real arithmetic and only checking it was
    called is a different kind of unverified behavior entirely, so this
    verifies the fallback clause holds for a case the model was never
    shown, not just the one literal example."""
    pairing = _pairing("out_of_scope_low_mocked_away_source.py", "out_of_scope_low_mocked_away_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_partially_tested_code_is_flagged_for_the_gaps_only(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("partially_tested_source.py", "partially_tested_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_no_test_file_submitted_is_stated_explicitly(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("no_test_source.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents != []
    assert any(
        "test file" in incident.description.lower() and " no " in f" {incident.description.lower()} "
        for incident in entry.incidents
    )


def test_concurrent_state_without_concurrent_tests_is_flagged(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("concurrent_source.py", "concurrent_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents != []


def test_high_priority_scenario_is_flagged_high(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("priority_high_source.py", "priority_high_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("priority_medium_source.py", "priority_medium_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("priority_low_source.py", "priority_low_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(test_gap_agent: CoverageGapAgent) -> None:
    """Vacuous assertions that exercise every path without verifying
    anything are coverage-adjacent but outside TCASE's three in-scope
    considerations, so they must still be reported, but only at priority
    low."""
    pairing = _pairing("priority_out_of_scope_low_source.py", "priority_out_of_scope_low_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


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
