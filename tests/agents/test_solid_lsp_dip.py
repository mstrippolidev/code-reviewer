"""
    Tests for the SOLID2 agent (LSP + ISP + DIP). Content-based checks run
    against a real small local model, per this project's approach to
    LLM-backed tests. The hard-limit short-circuit test needs no LLM at
    all — it's the first FileSizeAwareAgentBase agent, so it isn't marked
    with pytest.mark.llm like the rest of this file.
"""
import pytest

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.solid_2 import SolidLspDipAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def solid2_agent(small_llm) -> SolidLspDipAgent:
    return SolidLspDipAgent(llm=small_llm)


@pytest.mark.llm
def test_clean_code_is_not_flagged(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("shared/clean_service.py")

    result = solid2_agent.execute_agent(code, file_path="clean_service.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.SOLID2
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_good_solid2_is_not_flagged(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/good_solid2.py")

    result = solid2_agent.execute_agent(code, file_path="good_solid2.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_internal_scalar_state_is_not_flagged_as_dip_violation(solid2_agent: SolidLspDipAgent) -> None:
    """A private counter is internal state, not a swappable collaborator
    — the prompt's own carve-out for item 3."""
    code = load_fixture("solid2/false_positive_internal_scalar_state.py")

    result = solid2_agent.execute_agent(code, file_path="false_positive_internal_scalar_state.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_covariant_override_is_not_flagged_as_lsp_violation(solid2_agent: SolidLspDipAgent) -> None:
    """Accepting a broader input and returning a more specific type
    honors the parent's contract; a caller relying on the parent type is
    never surprised."""
    code = load_fixture("solid2/false_positive_covariant_override.py")

    result = solid2_agent.execute_agent(code, file_path="false_positive_covariant_override.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_cohesive_small_interface_is_not_flagged_as_isp_violation(solid2_agent: SolidLspDipAgent) -> None:
    """Every method on this two-method Protocol is genuinely part of one
    coherent contract, with a real implementation on every implementer."""
    code = load_fixture("solid2/false_positive_cohesive_small_interface.py")

    result = solid2_agent.execute_agent(code, file_path="false_positive_cohesive_small_interface.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_lsp_violation_is_flagged(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/lsp_violation.py")

    result = solid2_agent.execute_agent(code, file_path="lsp_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_isp_violation_is_flagged(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/isp_violation.py")

    result = solid2_agent.execute_agent(code, file_path="isp_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_dip_violation_is_flagged(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/dip_violation.py")

    result = solid2_agent.execute_agent(code, file_path="dip_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/lsp_violation.py")

    result = solid2_agent.execute_agent(code, file_path="lsp_violation.py")

    assert all(entry.file_path == "lsp_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/priority_high.py")

    result = solid2_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/priority_medium.py")

    result = solid2_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/priority_low.py")

    result = solid2_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(solid2_agent: SolidLspDipAgent) -> None:
    """An isinstance check that special-cases a concrete subclass is
    DIP-adjacent but outside SOLID2's four in-scope categories, so it must
    still be reported, but only at priority low."""
    code = load_fixture("solid2/priority_out_of_scope_low.py")

    result = solid2_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_leaky_kwargs_passthrough_out_of_scope_is_flagged_low(solid2_agent: SolidLspDipAgent) -> None:
    """Generalization check, deliberately independent of the worked
    example now in SOLID2's prompt (isinstance special-casing): blindly
    forwarding **kwargs into an injected abstraction is a different
    DIP-adjacent smell entirely, so this verifies the fallback clause
    holds for a case the model was never shown, not just the one literal
    example."""
    code = load_fixture("solid2/out_of_scope_low_leaky_kwargs_passthrough.py")

    result = solid2_agent.execute_agent(code, file_path="out_of_scope_low_leaky_kwargs_passthrough.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(solid2_agent: SolidLspDipAgent) -> None:
    code = "x\n" * 900

    result = solid2_agent.execute_agent(
        code, file_path="huge_file.py", review_meta=FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED)
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.SOLID2
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(solid2_agent: SolidLspDipAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str, repo_data=None):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(SolidLspDipAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        solid2_agent.execute_agent(
            "x = 1", file_path="tiny.py", review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL)
        )

    assert invoked["called"] is True
