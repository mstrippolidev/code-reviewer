"""
    Tests for the CMPLX agent (complexity), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.schemas.review import CodeKey
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


def test_file_path_is_stamped_on_every_entry(complexity_agent: ComplexityAgent) -> None:
    code = load_fixture("complexity/deeply_nested_conditionals.py")

    result = complexity_agent.execute_agent(code, file_path="deeply_nested_conditionals.py")

    assert all(entry.file_path == "deeply_nested_conditionals.py" for entry in result.review)
