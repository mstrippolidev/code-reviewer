"""
    Tests for the SOLID1 agent (SRP + OCP). The content-based checks live in
    tests/fixtures/solid1/labels.json and run in test_agent_labels.py against
    a real small local model. The hard-limit short-circuit test needs no LLM
    at all — SOLID1 is a FileSizeAwareAgentBase agent, same as SOLID2, so it
    isn't marked with pytest.mark.llm.
"""
import pytest

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.solid_1 import SolidSrpOcpAgent
from code_reviewer.schemas.review import CodeKey, Priority, SizeStatus
from tests.helpers import load_fixture


@pytest.fixture
def solid1_agent(small_llm) -> SolidSrpOcpAgent:
    return SolidSrpOcpAgent(llm=small_llm)


@pytest.mark.llm
def test_file_path_is_stamped_on_every_entry(solid1_agent: SolidSrpOcpAgent) -> None:
    code = load_fixture("solid1/srp_class_violation.py")

    result = solid1_agent.execute_agent(code, file_path="srp_class_violation.py")

    assert all(entry.file_path == "srp_class_violation.py" for entry in result.review)


def test_hard_limit_exceeded_short_circuits_without_an_llm_call(solid1_agent: SolidSrpOcpAgent) -> None:
    code = "x\n" * 900

    result = solid1_agent.execute_agent(
        code, file_path="huge_file.py", review_meta=FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED)
    )

    entry = result.review[0]
    assert entry.rating == 0
    assert entry.code_key == CodeKey.SOLID1
    assert entry.incidents[0].priority == Priority.HIGH
    assert entry.incidents[0].line_position == "1-900"


def test_normal_size_status_does_not_short_circuit(solid1_agent: SolidSrpOcpAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    invoked = {}

    def fake_invoke(self, code: str, repo_data=None):
        invoked["called"] = True
        raise AssertionError("stop before a real LLM call")

    monkeypatch.setattr(SolidSrpOcpAgent, "_invoke", fake_invoke)

    with pytest.raises(AssertionError, match="stop before a real LLM call"):
        solid1_agent.execute_agent(
            "x = 1", file_path="tiny.py", review_meta=FileReviewMeta(size_status=SizeStatus.NORMAL)
        )

    assert invoked["called"] is True
