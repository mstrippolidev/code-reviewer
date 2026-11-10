"""
    Tests for the TEST agent (testability), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed
    tests. TEST is a plain AgentBase chunk agent, so there's no hard-limit
    short-circuit to test here, unlike the FileSizeAwareAgentBase file
    agents (SOLID2, COH, COUP). What each fixture should produce lives in
    tests/fixtures/test/labels.json and is checked in test_agent_labels.py.
"""
import pytest

from code_reviewer.agents.testability import TestabilityAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def test_agent(small_llm) -> TestabilityAgent:
    return TestabilityAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/hardcoded_dependency_violation.py")

    result = test_agent.execute_agent(code, file_path="hardcoded_dependency_violation.py")

    assert all(entry.file_path == "hardcoded_dependency_violation.py" for entry in result.review)
