"""
    A CMPLX call-depth fixture: one file, or a folder that stands in for a
    small project. Reports are built by the real CallDepthReportBuilder, the
    step run_pipeline runs before dispatch.
"""
from pathlib import Path

from code_reviewer.pipeline.call_depth.depth_follower import DepthReport
from code_reviewer.pipeline.call_depth.report_builder import CallDepthReportBuilder
from code_reviewer.schemas.review import SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from tests.helpers import FIXTURES_DIR


class CallDepthScenario:
    def __init__(self, fixture: str) -> None:
        self._sources = self._read(FIXTURES_DIR / fixture)

    def code(self, path: str) -> str:
        return self._sources[path]

    def reports_for(self, path: str) -> list[DepthReport]:
        built = CallDepthReportBuilder().build([self._prepared(file_path) for file_path in self._sources])
        return next(file.call_depth_reports for file in built if file.source_file.file_path == path)

    def report_for(self, path: str, function: str) -> DepthReport:
        return next(report for report in self.reports_for(path) if report.function == function)

    def _read(self, root: Path) -> dict[str, str]:
        if root.is_file():
            return {root.name: root.read_text()}
        return {file.relative_to(root).as_posix(): file.read_text() for file in sorted(root.rglob("*.py"))}

    def _prepared(self, path: str) -> PreparedFile:
        return PreparedFile(
            source_file=SubmittedFile(file_path=path, content=self._sources[path]),
            size_status=SizeStatus.NORMAL,
        )
