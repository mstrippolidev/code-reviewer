"""
    Tests for the SOLID1 agent (SRP + OCP). Content-based checks run
    against a real small local model, per this project's approach to
    LLM-backed tests. The hard-limit short-circuit test needs no LLM at
    all — SOLID1 is a FileSizeAwareAgentBase agent, same as SOLID2, so it
    isn't marked with pytest.mark.llm like the rest of this file.
"""
import pytest

from code_reviewer.agents.solid_1 import SolidSrpOcpAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def solid1_agent(small_llm) -> SolidSrpOcpAgent:
    return SolidSrpOcpAgent(llm=small_llm)


@pytest.mark.llm
def test_clean_code_is_not_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = solid1_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.SOLID1
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_good_solid1_is_not_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/good_solid1.py")

    result = solid1_agent.execute_agent(code, file_path="good_solid1.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_srp_class_violation_is_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/srp_class_violation.py")

    result = solid1_agent.execute_agent(code, file_path="srp_class_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_ocp_violation_is_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/ocp_violation.py")

    result = solid1_agent.execute_agent(code, file_path="ocp_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_srp_function_violation_is_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/srp_function_violation.py")

    result = solid1_agent.execute_agent(code, file_path="srp_function_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_too_many_params_is_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/too_many_params_violation.py")

    result = solid1_agent.execute_agent(code, file_path="too_many_params_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_boolean_flag_argument_is_flagged(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/boolean_flag_violation.py")

    result = solid1_agent.execute_agent(code, file_path="boolean_flag_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/srp_class_violation.py")

    result = solid1_agent.execute_agent(code, file_path="srp_class_violation.py")

    assert all(entry.file_path == "srp_class_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/priority_high.py")

    result = solid1_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/priority_medium.py")

    result = solid1_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/priority_low.py")

    result = solid1_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(solid1_agent: SolidSrpOcpAgent) -> None:
    """Temporal coupling is SRP/OCP-adjacent but outside SOLID1's five
    in-scope categories, so it must still be reported, but only at
    priority low."""
    code = load_fixture("solid1/priority_out_of_scope_low.py")

    result = solid1_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(solid1_agent: SolidSrpOcpAgent) -> None:
    code = "x\n" * 900

    result = solid1_agent.execute_agent(
        code, file_path="huge_file.py", size_status=SizeStatus.HARD_LIMIT_EXCEEDED
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.SOLID1
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(solid1_agent: SolidSrpOcpAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(SolidSrpOcpAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        solid1_agent.execute_agent("x = 1", file_path="tiny.py", size_status=SizeStatus.NORMAL)

    assert invoked["called"] is True
