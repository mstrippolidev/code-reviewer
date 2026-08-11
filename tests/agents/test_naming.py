"""
    Tests for the VAR agent (naming quality), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.naming import NamingAgent
from code_reviewer.schemas.review import CodeKey
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def naming_agent(small_llm) -> NamingAgent:
    return NamingAgent(llm=small_llm)


def test_clean_code_is_not_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = naming_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.VAR
    assert entry.incidents == []
    assert entry.rating == 100


def test_acceptable_short_names_are_not_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/acceptable_short_names.py")

    result = naming_agent.execute_agent(code, file_path="acceptable_short_names.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_similar_but_distinct_names_are_not_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/similar_but_distinct_names.py")

    result = naming_agent.execute_agent(code, file_path="similar_but_distinct_names.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_bad_abbreviations_are_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/bad_abbreviations.py")

    result = naming_agent.execute_agent(code, file_path="bad_abbreviations.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_vague_names_are_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/vague_names.py")

    result = naming_agent.execute_agent(code, file_path="vague_names.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_inconsistent_vocabulary_is_flagged(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/inconsistent_vocabulary.py")

    result = naming_agent.execute_agent(code, file_path="inconsistent_vocabulary.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_file_path_is_stamped_on_every_entry(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/bad_abbreviations.py")

    result = naming_agent.execute_agent(code, file_path="bad_abbreviations.py")

    assert all(entry.file_path == "bad_abbreviations.py" for entry in result.review)
