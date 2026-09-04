"""
    Rewrites an incident's line_position from chunk-relative to
    file-absolute, using the chunk's own start_line in the real file.
    Shared by dispatch's chunk-agent merging and the DRY judge, which both
    hand a model a code snippet that starts, from the model's point of
    view, at line 1.
"""
from code_reviewer.schemas.review import Incident


def offset_incidents(incidents: list[Incident], start_line: int) -> list[Incident]:
    return [
        incident.model_copy(update={"line_position": offset_line_position(incident.line_position, start_line)})
        for incident in incidents
    ]


def offset_line_position(line_position: str, start_line: int) -> str:
    try:
        chunk_start, chunk_end = _parse_line_range(line_position)
    except ValueError:
        return line_position
    file_offset = start_line - 1
    return f"{chunk_start + file_offset}-{chunk_end + file_offset}"


def _parse_line_range(line_position: str) -> tuple[int, int]:
    start_text, end_text = line_position.split("-")
    return int(start_text), int(end_text)
