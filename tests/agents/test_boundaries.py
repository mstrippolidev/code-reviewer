"""
    Tests for the BOUND agent (boundaries). The content-based checks live in
    tests/fixtures/bound/labels.json and run in test_agent_labels.py against
    a real small local model. The hard-limit short-circuit test needs no LLM
    at all — BOUND is a FileSizeAwareAgentBase agent, same as SOLID2/COH/
    COUP/ARCH, so it isn't marked with pytest.mark.llm.
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
def test_file_path_is_stamped_on_every_entry(bound_agent: BoundariesAgent) -> None:
    code = load_fixture("bound/leaked_representation_violation.py")

    result = bound_agent.execute_agent(code, file_path="leaked_representation_violation.py")

    assert all(entry.file_path == "leaked_representation_violation.py" for entry in result.review)


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
