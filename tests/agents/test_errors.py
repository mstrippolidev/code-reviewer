"""
    Tests for the ERR agent (error handling), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed tests.
"""
import pytest

from code_reviewer.agents.errors import ErrorsAgent
from code_reviewer.schemas.review import CodeKey, Priority
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def errors_agent(small_llm) -> ErrorsAgent:
    return ErrorsAgent(llm=small_llm)


def test_clean_code_is_not_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = errors_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.ERR
    assert entry.incidents == []
    assert entry.rating == 100


def test_good_error_handling_is_not_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/good_error_handling.py")

    result = errors_agent.execute_agent(code, file_path="good_error_handling.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_generic_exception_is_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/generic_exception_raised.py")

    result = errors_agent.execute_agent(code, file_path="generic_exception_raised.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_returns_error_code_is_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/returns_error_code.py")

    result = errors_agent.execute_agent(code, file_path="returns_error_code.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_swallowed_exception_is_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/swallowed_exception.py")

    result = errors_agent.execute_agent(code, file_path="swallowed_exception.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_dead_code_is_flagged(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/dead_code.py")

    result = errors_agent.execute_agent(code, file_path="dead_code.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_idiomatic_optional_return_is_not_flagged(errors_agent: ErrorsAgent) -> None:
    """Regression test: a None return for a legitimately absent value
    (a lookup miss) is not a failure signal and must not trigger item 1."""
    code = load_fixture("errors/idiomatic_optional_return.py")

    result = errors_agent.execute_agent(code, file_path="idiomatic_optional_return.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_high_priority_scenario_is_flagged_high(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/priority_high.py")

    result = errors_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/priority_medium.py")

    result = errors_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/priority_low.py")

    result = errors_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(errors_agent: ErrorsAgent) -> None:
    """A vague exception message is error-handling-adjacent but outside
    ERR's four in-scope categories, so it must still be reported, but only
    at priority low."""
    code = load_fixture("errors/priority_out_of_scope_low.py")

    result = errors_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_file_path_is_stamped_on_every_entry(errors_agent: ErrorsAgent) -> None:
    code = load_fixture("errors/generic_exception_raised.py")

    result = errors_agent.execute_agent(code, file_path="generic_exception_raised.py")

    assert all(entry.file_path == "generic_exception_raised.py" for entry in result.review)
