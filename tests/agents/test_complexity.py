"""
    Tests for the CMPLX agent (complexity), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
    What each fixture should produce lives in
    tests/fixtures/complexity/labels.json and is checked in
    test_complexity_call_depth.py.
"""
import pytest

from code_reviewer.agents.complexity import ComplexityAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def complexity_agent(small_llm) -> ComplexityAgent:
    return ComplexityAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/deeply_nested_conditionals.py")

    result = complexity_agent.execute_agent(code, file_path="deeply_nested_conditionals.py")

    assert all(entry.file_path == "deeply_nested_conditionals.py" for entry in result.review)
