"""
    Line-count check on a single file's content. Classifies files that are
    still worth reviewing, and rejects files too large to review even split
    into per-function/class chunks.
"""
from code_reviewer.config.settings import SIZE_STATUS_LINE_THRESHOLDS, get_settings
from code_reviewer.pipeline.errors import FileTooLargeError
from code_reviewer.schemas.review import SizeStatus


def run_file_size_guard(content: str) -> SizeStatus:
    """Classifies a file's size into normal/soft_limit/hard_limit_exceeded,
    or raises FileTooLargeError if it exceeds the absolute line cap."""
    line_count = content.count("\n")
    max_file_lines = get_settings().max_file_lines

    if line_count > max_file_lines:
        raise FileTooLargeError(
            f"File is {line_count} lines, exceeding the {max_file_lines} line cap."
        )
    if line_count < SIZE_STATUS_LINE_THRESHOLDS[SizeStatus.SOFT_LIMIT]:
        return SizeStatus.NORMAL
    if line_count <= SIZE_STATUS_LINE_THRESHOLDS[SizeStatus.HARD_LIMIT_EXCEEDED]:
        return SizeStatus.SOFT_LIMIT
    return SizeStatus.HARD_LIMIT_EXCEEDED
