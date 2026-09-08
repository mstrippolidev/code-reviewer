"""
    Tests for the CMPLX agent (complexity), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.schemas.review import CodeKey, Priority
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def complexity_agent(small_llm) -> ComplexityAgent:
    return ComplexityAgent(llm=small_llm)


def test_clean_code_is_not_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = complexity_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.CMPLX
    assert entry.incidents == []
    assert entry.rating == 100


def test_good_complexity_is_not_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/good_complexity.py")

    result = complexity_agent.execute_agent(code, file_path="good_complexity.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_two_level_nesting_is_not_flagged(complexity_agent: ComplexityAgent) -> None:
    """Two levels is the boundary itself, not a violation of item 1's
    'more than 2 levels deep'."""
    code = load_fixture("complexity/false_positive_two_level_nesting.py")

    result = complexity_agent.execute_agent(code, file_path="false_positive_two_level_nesting.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_three_part_condition_is_not_flagged(complexity_agent: ComplexityAgent) -> None:
    """Three parts is the boundary itself, not a violation of item 2's
    'more than 3 parts'."""
    code = load_fixture("complexity/false_positive_three_part_condition.py")

    result = complexity_agent.execute_agent(code, file_path="false_positive_three_part_condition.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_deeply_nested_conditionals_are_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/deeply_nested_conditionals.py")

    result = complexity_agent.execute_agent(code, file_path="deeply_nested_conditionals.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_complex_boolean_condition_is_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/complex_boolean_condition.py")

    result = complexity_agent.execute_agent(code, file_path="complex_boolean_condition.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_too_many_exit_points_is_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/too_many_exit_points.py")

    result = complexity_agent.execute_agent(code, file_path="too_many_exit_points.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_high_cyclomatic_complexity_is_flagged(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/high_cyclomatic_complexity.py")

    result = complexity_agent.execute_agent(code, file_path="high_cyclomatic_complexity.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_guard_clause_style_is_not_flagged(complexity_agent: ComplexityAgent) -> None:
    """Regression test: flat, top-level guard clauses are the preferred
    alternative to nesting and must not be flagged for exit-point count."""
    code = load_fixture("complexity/guard_clause_style.py")

    result = complexity_agent.execute_agent(code, file_path="guard_clause_style.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_high_priority_scenario_is_flagged_high(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/priority_high.py")

    result = complexity_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/priority_medium.py")

    result = complexity_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/priority_low.py")

    result = complexity_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(complexity_agent: ComplexityAgent) -> None:
    """Using a raised/caught exception for ordinary control flow is a real
    clarity problem outside CMPLX's four in-scope categories, so it must
    still be reported, but only at priority low."""
    code = load_fixture("complexity/priority_out_of_scope_low.py")

    result = complexity_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_file_path_is_stamped_on_every_entry(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/deeply_nested_conditionals.py")

    result = complexity_agent.execute_agent(code, file_path="deeply_nested_conditionals.py")

    assert all(entry.file_path == "deeply_nested_conditionals.py" for entry in result.review)
