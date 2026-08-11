"""
    Tests for the COH agent (cohesion). Content-based checks run against a
    real small local model, per this project's approach to LLM-backed
    tests. The hard-limit short-circuit test needs no LLM at all — COH is
    a FileSizeAwareAgentBase agent, same as SOLID1/SOLID2, so it isn't
    marked with pytest.mark.llm like the rest of this file.
"""
import pytest

from code_reviewer.agents.cohesion import CohesionAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def coh_agent(small_llm) -> CohesionAgent:
    return CohesionAgent(llm=small_llm)


@pytest.mark.llm
def test_clean_code_is_not_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = coh_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.COH
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_good_cohesion_is_not_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/good_cohesion.py")

    result = coh_agent.execute_agent(code, file_path="good_cohesion.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_bundled_concerns_violation_is_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/bundled_concerns_violation.py")

    result = coh_agent.execute_agent(code, file_path="bundled_concerns_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_disjoint_methods_violation_is_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/disjoint_methods_violation.py")

    result = coh_agent.execute_agent(code, file_path="disjoint_methods_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_grab_bag_module_violation_is_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/grab_bag_module_violation.py")

    result = coh_agent.execute_agent(code, file_path="grab_bag_module_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_method_ignores_self_violation_is_flagged(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/method_ignores_self_violation.py")

    result = coh_agent.execute_agent(code, file_path="method_ignores_self_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(coh_agent: CohesionAgent) -> None:
    code = load_fixture("coh/bundled_concerns_violation.py")

    result = coh_agent.execute_agent(code, file_path="bundled_concerns_violation.py")

    assert all(entry.file_path == "bundled_concerns_violation.py" for entry in result.review)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(coh_agent: CohesionAgent) -> None:
    code = "x\n" * 900

    result = coh_agent.execute_agent(
        code, file_path="huge_file.py", size_status=SizeStatus.HARD_LIMIT_EXCEEDED
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.COH
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(coh_agent: CohesionAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(CohesionAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        coh_agent.execute_agent("x = 1", file_path="tiny.py", size_status=SizeStatus.NORMAL)

    assert invoked["called"] is True
