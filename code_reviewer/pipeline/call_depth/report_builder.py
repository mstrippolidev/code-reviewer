"""
    Fills PreparedFile.call_depth_reports for every file of one submission.

    One ProjectFiles and one CallDepthFollower are built for the whole
    submission and shared by every file, so each file is parsed once and a
    call from one PR file into another resolves. For a registered repo, calls
    into files outside the PR are read from the index; a submission with no
    repo has no such fallback, so only the PR's own files are searched.

    A file is never dropped from the review because of its report: when the
    report for a file cannot be built, that file keeps an empty list.
    Non-Python files, standalone test files and files past the hard size
    limit are not walked.
"""
import logging

from code_reviewer.pipeline.call_depth.depth_follower import CallDepthFollower, DepthReport, UnknownEntry
from code_reviewer.pipeline.call_depth.project_files import ProjectFiles
from code_reviewer.pipeline.call_depth.thin_body import ThinBodyClassifier
from code_reviewer.rag.chunk_file_loader import ChunkFileLoader
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.schemas.review import ReviewScope, SizeStatus
from code_reviewer.schemas.submission import PreparedFile

logger = logging.getLogger(__name__)


class CallDepthReportBuilder:
    def __init__(self, rag_manager: LlamaIndexRagManager | None = None) -> None:
        self._rag_manager = rag_manager

    def build(self, prepared_files: list[PreparedFile]) -> list[PreparedFile]:
        follower = self._follower_for(prepared_files)
        return [self._with_reports(prepared_file, follower) for prepared_file in prepared_files]

    def _follower_for(self, prepared_files: list[PreparedFile]) -> CallDepthFollower:
        sources = {
            prepared_file.source_file.file_path: prepared_file.source_file.content
            for prepared_file in prepared_files
            if self._is_python(prepared_file)
        }
        return CallDepthFollower(ProjectFiles(sources, self._loader_for(prepared_files)), ThinBodyClassifier())

    def _loader_for(self, prepared_files: list[PreparedFile]) -> ChunkFileLoader | None:
        repo_data = next((file.repo_data for file in prepared_files if file.repo_data), None)
        if self._rag_manager is None or repo_data is None:
            return None
        return ChunkFileLoader(self._rag_manager, repo_data)

    def _with_reports(self, prepared_file: PreparedFile, follower: CallDepthFollower) -> PreparedFile:
        if not self._is_walked(prepared_file):
            return prepared_file
        return prepared_file.model_copy(update={"call_depth_reports": self._reports_for(prepared_file, follower)})

    def _reports_for(self, prepared_file: PreparedFile, follower: CallDepthFollower) -> list[DepthReport]:
        file_path = prepared_file.source_file.file_path
        try:
            return follower.reports_for(file_path)
        except UnknownEntry:
            return []
        except Exception:
            logger.exception("Call-depth report failed for file_path=%s; reviewing it without one", file_path)
            return []

    def _is_python(self, prepared_file: PreparedFile) -> bool:
        return prepared_file.source_file.file_path.endswith(".py")

    def _is_walked(self, prepared_file: PreparedFile) -> bool:
        return (
            self._is_python(prepared_file)
            and prepared_file.review_scope is ReviewScope.FULL
            and prepared_file.size_status is not SizeStatus.HARD_LIMIT_EXCEEDED
        )
