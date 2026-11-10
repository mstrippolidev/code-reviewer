"""
    Tests for the VAR agent (naming quality), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
    What each fixture should produce lives in
    tests/fixtures/naming/labels.json and is checked in test_agent_labels.py.
"""
import pytest

from code_reviewer.agents.naming import NamingAgent
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def naming_agent(small_llm) -> NamingAgent:
    return NamingAgent(llm=small_llm)


def test_file_path_is_stamped_on_every_entry(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/bad_abbreviations.py")

    result = naming_agent.execute_agent(code, file_path="bad_abbreviations.py")

    assert all(entry.file_path == "bad_abbreviations.py" for entry in result.review)
