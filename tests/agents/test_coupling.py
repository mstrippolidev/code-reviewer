"""
    Tests for the COUP agent (coupling). Content-based checks run against a
    real small local model, per this project's approach to LLM-backed
    tests. The hard-limit short-circuit test needs no LLM at all — COUP is
    a FileSizeAwareAgentBase agent, same as SOLID2/COH, so it isn't marked
    with pytest.mark.llm like the rest of this file.
"""
import pytest

from code_reviewer.agents.coupling import CouplingAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def coup_agent(small_llm) -> CouplingAgent:
    return CouplingAgent(llm=small_llm)


@pytest.mark.llm
def test_good_coupling_is_not_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/good_coupling.py")

    result = coup_agent.execute_agent(code, file_path="good_coupling.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.COUP
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_circular_dependency_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/circular_dependency_violation.py")

    result = coup_agent.execute_agent(code, file_path="circular_dependency_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_feature_envy_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/feature_envy_violation.py")

    result = coup_agent.execute_agent(code, file_path="feature_envy_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_inappropriate_intimacy_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/inappropriate_intimacy_violation.py")

    result = coup_agent.execute_agent(code, file_path="inappropriate_intimacy_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_god_object_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/god_object_violation.py")

    result = coup_agent.execute_agent(code, file_path="god_object_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_deep_chain_violation_is_flagged(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/deep_chain_violation.py")

    result = coup_agent.execute_agent(code, file_path="deep_chain_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/circular_dependency_violation.py")

    result = coup_agent.execute_agent(code, file_path="circular_dependency_violation.py")

    assert all(entry.file_path == "circular_dependency_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_high.py")

    result = coup_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_medium.py")

    result = coup_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(coup_agent: CouplingAgent) -> None:
    code = load_fixture("coup/priority_low.py")

    result = coup_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(coup_agent: CouplingAgent) -> None:
    """Common coupling through shared module-level state (two classes with
    no reference to each other, both reading and writing the same global)
    is coupling-adjacent but outside COUP's five in-scope categories, so
    it must still be reported, but only at priority low."""
    code = load_fixture("coup/priority_out_of_scope_low.py")

    result = coup_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(coup_agent: CouplingAgent) -> None:
    code = "x\n" * 900

    result = coup_agent.execute_agent(
        code, file_path="huge_file.py", size_status=SizeStatus.HARD_LIMIT_EXCEEDED
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.COUP
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(coup_agent: CouplingAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(CouplingAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        coup_agent.execute_agent("x = 1", file_path="tiny.py", size_status=SizeStatus.NORMAL)

    assert invoked["called"] is True
