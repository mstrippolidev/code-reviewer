"""
    Tests for the ERR agent (error handling), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
    What each fixture should produce lives in
    tests/fixtures/errors/labels.json and is checked in test_agent_labels.py.
"""
import pytest

from code_reviewer.agents.errors import ErrorsAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def errors_agent(small_llm) -> ErrorsAgent:
    return ErrorsAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/generic_exception_raised.py")

    result = errors_agent.execute_agent(code, file_path="generic_exception_raised.py")

    assert all(entry.file_path == "generic_exception_raised.py" for entry in result.review)
