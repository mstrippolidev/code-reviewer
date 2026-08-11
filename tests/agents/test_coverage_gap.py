"""
    Tests for the TCASE agent (test gap detection), run against a real
    small local model rather than a mock, per this project's approach to
    LLM-backed tests.
"""
import pytest

from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.review import CodeKey
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


def test_file_path_is_stamped_from_the_source_file(test_gap_agent: CoverageGapAgent) -> None:
    pairing = _pairing("partially_tested_source.py", "partially_tested_test.py")

    result = test_gap_agent.execute_agent(pairing.get_content(), file_path=pairing.source_file.file_path)

    assert all(entry.file_path == "partially_tested_source.py" for entry in result.review)
