"""
    Turns dry_matching.py's bare locations into duplicate-group evidence
    paired with real code: attach_code() reads each match's own file,
    groups_for_file() narrows a PR-wide result down to one file.
"""
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile


def extract_snippet(content: str, match: StructuralMatch) -> str:
    lines = content.splitlines()
    return "\n".join(lines[match.start_line - 1 : match.end_line])


def attach_code(files: list[SubmittedFile], groups: list[list[StructuralMatch]]) -> list[list[LocatedChunk]]:
    contents = {file.file_path: file.content for file in files}
    located_groups = []
    for group in groups:
        located_group = []
        for match in group:
            file_content = contents.get(match.file_path, "")
            code = extract_snippet(file_content, match)
            located_group.append(LocatedChunk(match, code))
        located_groups.append(located_group)
    return located_groups


def groups_for_file(groups: list[list[LocatedChunk]], file_path: str) -> list[list[LocatedChunk]]:
    return [group for group in groups if any(located.match.file_path == file_path for located in group)]
