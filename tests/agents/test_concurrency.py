"""
    Tests for the CONC agent (concurrency safety), run against a real
    small local model rather than a mock, per this project's approach to
    LLM-backed tests. CONC is a plain AgentBase chunk agent, so there's no
    hard-limit short-circuit to test here, unlike the FileSizeAwareAgentBase
    file agents (SOLID2, COH, COUP).
"""
import pytest

from code_reviewer.agents.concurrency import ConcurrencyAgent
from code_reviewer.schemas.review import CodeKey, Priority
from tests.helpers import load_fixture

pytestmark = pytest.mark.llm


@pytest.fixture
def conc_agent(small_llm) -> ConcurrencyAgent:
    return ConcurrencyAgent(llm=small_llm)


def test_good_concurrency_is_not_flagged(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/good_concurrency.py")

    result = conc_agent.execute_agent(code, file_path="good_concurrency.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.CONC
    assert entry.incidents == []
    assert entry.rating == 100


def test_unprotected_shared_state_violation_is_flagged(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/unprotected_shared_state_violation.py")

    result = conc_agent.execute_agent(code, file_path="unprotected_shared_state_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_race_condition_check_then_act_violation_is_flagged(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/race_condition_check_then_act_violation.py")

    result = conc_agent.execute_agent(code, file_path="race_condition_check_then_act_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_async_misuse_violation_is_flagged(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/async_misuse_violation.py")

    result = conc_agent.execute_agent(code, file_path="async_misuse_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_non_atomic_resource_violation_is_flagged(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/non_atomic_resource_violation.py")

    result = conc_agent.execute_agent(code, file_path="non_atomic_resource_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


def test_file_path_is_stamped_on_every_entry(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/unprotected_shared_state_violation.py")

    result = conc_agent.execute_agent(code, file_path="unprotected_shared_state_violation.py")

    assert all(entry.file_path == "unprotected_shared_state_violation.py" for entry in result.review)


def test_high_priority_scenario_is_flagged_high(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/priority_high.py")

    result = conc_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


def test_medium_priority_scenario_is_flagged_medium(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/priority_medium.py")

    result = conc_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


def test_low_priority_scenario_is_flagged_low(conc_agent: ConcurrencyAgent) -> None:
    code = load_fixture("conc/priority_low.py")

    result = conc_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


def test_out_of_scope_scenario_is_flagged_low(conc_agent: ConcurrencyAgent) -> None:
    """Unbounded concurrency (spawning tasks with no pool/limit) is
    concurrency-adjacent but outside CONC's four in-scope categories, so
    it must still be reported, but only at priority low."""
    code = load_fixture("conc/priority_out_of_scope_low.py")

    result = conc_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)
