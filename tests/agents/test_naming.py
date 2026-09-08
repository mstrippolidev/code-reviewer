"""
    Tests for the VAR agent (naming quality), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.naming import NamingAgent
from code_reviewer.schemas.review import CodeKey, Priority
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


def test_unexpressible_comment_is_not_flagged(naming_agent: NamingAgent) -> None:
    """The comment states a business rule no identifier could carry, not
    a unit or qualifier the name omitted."""
    code = load_fixture("naming/false_positive_unexpressible_comment.py")

    result = naming_agent.execute_agent(code, file_path="false_positive_unexpressible_comment.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_different_concepts_with_different_verbs_are_not_flagged(naming_agent: NamingAgent) -> None:
    """fetch_user and get_cached_region name two genuinely different
    operations, not the same concept named two inconsistent ways."""
    code = load_fixture("naming/false_positive_different_concepts_different_verbs.py")

    result = naming_agent.execute_agent(code, file_path="false_positive_different_concepts_different_verbs.py")

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


def test_high_priority_scenario_is_flagged_high(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/priority_high.py")

    result = naming_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/priority_medium.py")

    result = naming_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/priority_low.py")

    result = naming_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(naming_agent: NamingAgent) -> None:
    """Variable shadowing is naming-adjacent but outside VAR's four
    in-scope categories — the prompt's own example of a real finding that
    must still be reported, but only at priority low."""
    code = load_fixture("naming/priority_out_of_scope_low.py")

    result = naming_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_file_path_is_stamped_on_every_entry(naming_agent: NamingAgent) -> None:
    code = load_fixture("naming/bad_abbreviations.py")

    result = naming_agent.execute_agent(code, file_path="bad_abbreviations.py")

    assert all(entry.file_path == "bad_abbreviations.py" for entry in result.review)
