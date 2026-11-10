"""
    Tests for the SOLID2 agent (LSP + ISP + DIP). The content-based checks
    live in tests/fixtures/solid2/labels.json and run in test_agent_labels.py
    against a real small local model. The hard-limit short-circuit test needs
    no LLM at all — it's the first FileSizeAwareAgentBase agent, so it isn't
    marked with pytest.mark.llm.
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
def test_file_path_is_stamped_on_every_entry(solid2_agent: SolidLspDipAgent) -> None:
    code = load_fixture("solid2/lsp_violation.py")

    result = solid2_agent.execute_agent(code, file_path="lsp_violation.py")

    assert all(entry.file_path == "lsp_violation.py" for entry in result.review)


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
