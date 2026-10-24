"""
    Tests for what the CMPLX agent hands the model, with the model call
    replaced: the numbered file, the call-depth report block, and the
    hard-limit short-circuit. No LLM.
"""
import pytest

from code_reviewer.agents.base import FileReviewMeta
from code_reviewer.agents.complexity import CALL_DEPTH_REPORT_HEADER, ComplexityAgent
from code_reviewer.pipeline.call_depth.depth_follower import CallDepth, DepthReport, WalkEnd
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Priority, SizeStatus

CODE = "def route():\n    return helper()\n"

REPORT = DepthReport(
    function="route",
    path="app/router.py",
    calls=[
        CallDepth(
            callee="helper",
            line=2,
            hops_in_file=1,
            hops_in_other_files=0,
            other_files=[],
            ended_at=WalkEnd.REAL_LOGIC,
        )
    ],
)


@pytest.fixture
def model_inputs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    received: list[str] = []

    def fake_invoke(self: ComplexityAgent, code: str, repo_data: object = None) -> AgentOutput:
        received.append(code)
        return AgentOutput(review=[AgentReviewEntry(code_key=CodeKey.CMPLX, incidents=[])])

    monkeypatch.setattr(ComplexityAgent, "_invoke", fake_invoke)
    return received


def test_every_line_of_the_file_is_numbered(model_inputs: list[str]) -> None:
    ComplexityAgent().execute_agent(CODE, "app/router.py")

    assert model_inputs == ["1: def route():\n2:     return helper()"]


def test_reports_are_appended_after_the_code_under_the_header(model_inputs: list[str]) -> None:
    ComplexityAgent().execute_agent(CODE, "app/router.py", FileReviewMeta(call_depth_reports=[REPORT]))

    expected_tail = f"\n\n{CALL_DEPTH_REPORT_HEADER}\n{REPORT.to_prompt_text()}"
    assert model_inputs[0] == "1: def route():\n2:     return helper()" + expected_tail


def test_each_report_adds_its_own_block(model_inputs: list[str]) -> None:
    other = REPORT.model_copy(update={"function": "other_route"})

    ComplexityAgent().execute_agent(CODE, "app/router.py", FileReviewMeta(call_depth_reports=[REPORT, other]))

    assert model_inputs[0].endswith(f"{REPORT.to_prompt_text()}\n{other.to_prompt_text()}")


def test_no_reports_means_no_header(model_inputs: list[str]) -> None:
    ComplexityAgent().execute_agent(CODE, "app/router.py", FileReviewMeta(call_depth_reports=[]))

    assert CALL_DEPTH_REPORT_HEADER not in model_inputs[0]


def test_hard_limit_file_is_rated_zero_without_calling_the_model(model_inputs: list[str]) -> None:
    code = "x = 1\n" * 900
    meta = FileReviewMeta(size_status=SizeStatus.HARD_LIMIT_EXCEEDED, call_depth_reports=[REPORT])

    entry = ComplexityAgent().execute_agent(code, "huge.py", meta).review[0]

    assert (model_inputs, entry.rating, entry.incidents[0].priority, entry.incidents[0].line_position) == (
        [],
        0,
        Priority.HIGH,
        "1-900",
    )


def test_the_file_path_and_code_key_are_stamped_on_the_result(model_inputs: list[str]) -> None:
    entry = ComplexityAgent().execute_agent(CODE, "app/router.py").review[0]

    assert (entry.file_path, entry.code_key) == ("app/router.py", CodeKey.CMPLX)
