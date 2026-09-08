"""
    Tests for the TEST agent (testability), run against a real small local
    model rather than a mock, per this project's approach to LLM-backed
    tests. TEST is a plain AgentBase chunk agent, so there's no hard-limit
    short-circuit to test here, unlike the FileSizeAwareAgentBase file
    agents (SOLID2, COH, COUP).
"""
import pytest

from code_reviewer.agents.testability import TestabilityAgent
from code_reviewer.schemas.review import CodeKey, Priority
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def test_agent(small_llm) -> TestabilityAgent:
    return TestabilityAgent(llm=small_llm)


def test_good_testability_is_not_flagged(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/good_testability.py")

    result = test_agent.execute_agent(code, file_path="good_testability.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.TEST
    assert entry.incidents == []
    assert entry.rating == 100


def test_internal_value_object_is_not_flagged_as_hard_coded_dependency(test_agent: TestabilityAgent) -> None:
    """A private field building a plain immutable value object has
    nothing a unit test would ever need to fake or stub."""
    code = load_fixture("test/false_positive_internal_value_object.py")

    result = test_agent.execute_agent(code, file_path="false_positive_internal_value_object.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_immutable_module_constant_is_not_flagged_as_hidden_global_state(test_agent: TestabilityAgent) -> None:
    """A constant that is never written to gives every test the same
    value every time, with nothing to isolate between runs."""
    code = load_fixture("test/false_positive_immutable_module_constant.py")

    result = test_agent.execute_agent(code, file_path="false_positive_immutable_module_constant.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_trivial_staticmethod_is_not_flagged_as_hidden_logic(test_agent: TestabilityAgent) -> None:
    """A one-line pure formula needs no injection point to be exercised
    in isolation — item 3 targets non-trivial branching logic."""
    code = load_fixture("test/false_positive_trivial_staticmethod.py")

    result = test_agent.execute_agent(code, file_path="false_positive_trivial_staticmethod.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_hardcoded_dependency_violation_is_flagged(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/hardcoded_dependency_violation.py")

    result = test_agent.execute_agent(code, file_path="hardcoded_dependency_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_hidden_global_state_violation_is_flagged(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/hidden_global_state_violation.py")

    result = test_agent.execute_agent(code, file_path="hidden_global_state_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_static_method_complexity_violation_is_flagged(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/static_method_complexity_violation.py")

    result = test_agent.execute_agent(code, file_path="static_method_complexity_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_excessive_dependencies_violation_is_flagged(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/excessive_dependencies_violation.py")

    result = test_agent.execute_agent(code, file_path="excessive_dependencies_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_file_path_is_stamped_on_every_entry(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/hardcoded_dependency_violation.py")

    result = test_agent.execute_agent(code, file_path="hardcoded_dependency_violation.py")

    assert all(entry.file_path == "hardcoded_dependency_violation.py" for entry in result.review)


def test_high_priority_scenario_is_flagged_high(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/priority_high.py")

    result = test_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/priority_medium.py")

    result = test_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(test_agent: TestabilityAgent) -> None:
    code = load_fixture("test/priority_low.py")

    result = test_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(test_agent: TestabilityAgent) -> None:
    """A function whose only observable behavior is a print statement is
    testability-adjacent but outside TEST's four in-scope categories, so
    it must still be reported, but only at priority low."""
    code = load_fixture("test/priority_out_of_scope_low.py")

    result = test_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)
