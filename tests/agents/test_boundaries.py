"""
    Tests for the BOUND agent (boundaries). Content-based checks run
    against a real small local model, per this project's approach to
    LLM-backed tests. The hard-limit short-circuit test needs no LLM at
    all — BOUND is a FileSizeAwareAgentBase agent, same as SOLID2/COH/
    COUP/ARCH, so it isn't marked with pytest.mark.llm like the rest of
    this file.
"""
import pytest

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.boundaries import BoundariesAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def bound_agent(small_llm) -> BoundariesAgent:
    return BoundariesAgent(llm=small_llm)


@pytest.mark.llm
def test_good_boundaries_is_not_flagged(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/good_boundaries.py")

    result = bound_agent.execute_agent(code, file_path="good_boundaries.py")

    entry = result.review[0]
    assert entry.code_key == CodeKey.BOUND
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_leaked_representation_violation_is_flagged(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/leaked_representation_violation.py")

    result = bound_agent.execute_agent(code, file_path="leaked_representation_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_unmarked_private_state_violation_is_flagged(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/unmarked_private_state_violation.py")

    result = bound_agent.execute_agent(code, file_path="unmarked_private_state_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_oversized_surface_violation_is_flagged(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/oversized_surface_violation.py")

    result = bound_agent.execute_agent(code, file_path="oversized_surface_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_library_type_leakage_violation_is_flagged(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/library_type_leakage_violation.py")

    result = bound_agent.execute_agent(code, file_path="library_type_leakage_violation.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert entry.rating < 100


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/leaked_representation_violation.py")

    result = bound_agent.execute_agent(code, file_path="leaked_representation_violation.py")

    assert all(entry.file_path == "leaked_representation_violation.py" for entry in result.review)


@pytest.mark.llm
def test_high_priority_scenario_is_flagged_high(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/priority_high.py")

    result = bound_agent.execute_agent(code, file_path="priority_high.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.HIGH for incident in entry.incidents)


@pytest.mark.llm
def test_medium_priority_scenario_is_flagged_medium(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/priority_medium.py")

    result = bound_agent.execute_agent(code, file_path="priority_medium.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.MEDIUM for incident in entry.incidents)


@pytest.mark.llm
def test_low_priority_scenario_is_flagged_low(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/priority_low.py")

    result = bound_agent.execute_agent(code, file_path="priority_low.py")

    entry = result.review[0]
    assert any(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_out_of_scope_scenario_is_flagged_low(bound_agent: BoundariesAgent) -> None:
    """A method whose only privacy signal is a docstring rather than an
    actual naming convention is boundary-adjacent but outside BOUND's
    four in-scope categories, so it must still be reported, but only at
    priority low."""
    code = load_fixture("bound/priority_out_of_scope_low.py")

    result = bound_agent.execute_agent(code, file_path="priority_out_of_scope_low.py")

    entry = result.review[0]
    assert entry.incidents != []
    assert all(incident.priority == Priority.LOW for incident in entry.incidents)


@pytest.mark.llm
def test_defensive_copy_is_not_flagged_as_leaked_representation(bound_agent: BoundariesAgent) -> None:
    """A method returning a copy of its internal list, never the live
    reference, must not be mistaken for leaking mutable state."""
    code = load_fixture("bound/false_positive_defensive_copy.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_defensive_copy.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_necessary_public_api_is_not_flagged_as_oversized(bound_agent: BoundariesAgent) -> None:
    """A small class whose every public method is core to its purpose
    must not be mistaken for an oversized surface."""
    code = load_fixture("bound/false_positive_necessary_public_api.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_necessary_public_api.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_wrapped_library_type_is_not_flagged_as_leakage(bound_agent: BoundariesAgent) -> None:
    """A repository that converts a library response into its own domain
    type before returning must not be mistaken for leaking that library's
    types across the boundary."""
    code = load_fixture("bound/false_positive_wrapped_library_type.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_wrapped_library_type.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_protected_for_subclasses_is_not_flagged(bound_agent: BoundariesAgent) -> None:
    """An underscore-prefixed attribute used only within its own class
    hierarchy is exactly what the naming convention is for, not a
    violation of it."""
    code = load_fixture("bound/false_positive_protected_for_subclasses.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_protected_for_subclasses.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_typed_parameter_is_not_flagged(bound_agent: BoundariesAgent) -> None:
    """A method taking a well-defined dataclass parameter must not be
    mistaken for the untyped-boundary out-of-scope case."""
    code = load_fixture("bound/false_positive_typed_parameter.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_typed_parameter.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


@pytest.mark.llm
def test_read_only_property_is_not_flagged(bound_agent: BoundariesAgent) -> None:
    """Exposing an immutable value through a read-only property, with no
    setter, must not be mistaken for leaking mutable internal state."""
    code = load_fixture("bound/false_positive_read_only_property.py")

    result = bound_agent.execute_agent(code, file_path="false_positive_read_only_property.py")

    entry = result.review[0]
    assert entry.incidents == []
    assert entry.rating == 100


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(bound_agent: BoundariesAgent) -> None:
    code = "x\n" * 900

    result = bound_agent.execute_agent(
        code, file_path="huge_file.py", review_meta=FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED)
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.BOUND
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(bound_agent: BoundariesAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str, repo_data=None):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(BoundariesAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        bound_agent.execute_agent(
            "x = 1", file_path="tiny.py", review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL)
        )

    assert invoked["called"] is True
