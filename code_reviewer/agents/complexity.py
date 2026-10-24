"""
    CMPLX agent: reviews logic complexity — nesting depth, condition size,
    exit points, cyclomatic complexity, and the hops a call takes to reach
    real logic.

    It reviews the whole file with every line numbered. When the file has
    call-depth reports, they are appended after the code under
    CALL_DEPTH_REPORT_HEADER, one block per function or method.
"""

from code_reviewer.agents.base import FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.pipeline.call_depth.depth_follower import DepthReport
from code_reviewer.prompts.agents.complexity import CMPLX_AGENT_SYSTEM_PROMPT
from code_reviewer.prompts.agents.line_numbering import number_lines
from code_reviewer.schemas.review import AgentOutput, CodeKey, SizeStatus

CALL_DEPTH_REPORT_HEADER = "CALL DEPTH REPORT"


class ComplexityAgent(FileSizeAwareAgentBase):
    """Reviews complexity: nesting depth, boolean condition size, exit points, cyclomatic complexity, and call depth."""

    def __init__(self, llm: LLMInterface | None = None) -> None:
        super().__init__(CodeKey.CMPLX, CMPLX_AGENT_SYSTEM_PROMPT, llm)

    def execute_agent(
        self, code: str, file_path: str | None = None, review_meta: FileReviewMeta | None = None
    ) -> AgentOutput:
        review_meta = review_meta or FileReviewMeta()
        if review_meta.size_status is SizeStatus.HARD_LIMIT_EXCEEDED:
            return super().execute_agent(code, file_path, review_meta)
        review_input = self._review_input(code, review_meta.call_depth_reports)
        return super().execute_agent(review_input, file_path, review_meta)

    def _review_input(self, code: str, reports: list[DepthReport]) -> str:
        numbered_code = number_lines(code)
        if not reports:
            return numbered_code
        report_text = "\n".join(report.to_prompt_text() for report in reports)
        return f"{numbered_code}\n\n{CALL_DEPTH_REPORT_HEADER}\n{report_text}"
