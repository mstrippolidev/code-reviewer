"""
    Builds the text DRY's LLM reads: turns dry_matching.py's bare
    locations into a report with the actual code at each location, where
    that code is available. attach_code() pairs each location with its
    code; DryEvidence.format() turns the result into that report.
"""
from dataclasses import dataclass
from typing import Protocol

from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import LocatedChunk, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile


class _LocatedChunk(Protocol):
    """Shape shared by StructuralMatch and SimilarChunk, so one function
    can format either as a location."""

    file_path: str
    chunk_name: str
    start_line: int
    end_line: int


def _format_location(chunk: _LocatedChunk, extra: str = "") -> str:
    """Formats a chunk's location as one short line, optionally with an
    extra detail (e.g. a similarity score) inside the same parentheses."""
    detail = f", {extra}" if extra else ""
    return f"{chunk.file_path}:{chunk.chunk_name} (lines {chunk.start_line}-{chunk.end_line}{detail})"


def _format_snippet(code: str) -> str:
    """Wraps code in a markdown code block."""
    return f"```\n{code}\n```"


def _extract_snippet(content: str, match: StructuralMatch) -> str:
    """Reads out just the lines a match points to, from a file's full content."""
    lines = content.splitlines()
    return "\n".join(lines[match.start_line - 1 : match.end_line])


def attach_code(files: list[SubmittedFile], groups: list[list[StructuralMatch]]) -> list[list[LocatedChunk]]:
    """Looks up each match's file and pairs the match with its own code."""
    contents = {file.file_path: file.content for file in files}
    located_groups = []
    for group in groups:
        located_group = []
        for match in group:
            file_content = contents.get(match.file_path, "")
            code = _extract_snippet(file_content, match)
            located_group.append(LocatedChunk(match, code))
        located_groups.append(located_group)
    return located_groups


def groups_for_file(groups: list[list[LocatedChunk]], file_path: str) -> list[list[LocatedChunk]]:
    """Keeps only the groups that include a match in the given file."""
    return [group for group in groups if any(located.match.file_path == file_path for located in group)]


@dataclass
class DryEvidence:
    """One file's duplication evidence, ready to turn into DRY's LLM input."""

    file_path: str
    file_content: str
    intra_pr_groups: list[list[LocatedChunk]]
    history_matches: list[ChunkHistoryMatch]

    def has_matches(self) -> bool:
        """True if there is any duplication evidence at all."""
        return bool(self.intra_pr_groups) or bool(self.history_matches)

    def format(self) -> str:
        """Builds the full evidence report as one string."""
        sections = [f"File under review: {self.file_path}"]
        if self.intra_pr_groups:
            sections.append(self._format_intra_pr_section())
        if self.history_matches:
            sections.append(self._format_history_section())
        return "\n\n".join(sections)

    def _format_intra_pr_section(self) -> str:
        """Renders every intra-PR duplicate group."""
        groups_text = "\n\n".join(
            self._format_group(index, group) for index, group in enumerate(self.intra_pr_groups, start=1)
        )
        return f"DUPLICATE GROUPS WITHIN THIS PR (chunks sharing identical structure):\n\n{groups_text}"

    def _format_group(self, index: int, group: list[LocatedChunk]) -> str:
        """Renders one duplicate group: every location in it, with code."""
        locations = "\n".join(f"- {_format_location(located.match)}\n{_format_snippet(located.code)}" for located in group)
        return f"Group {index}:\n{locations}"

    def _format_history_section(self) -> str:
        """Renders every chunk that duplicates something already indexed."""
        entries = "\n\n".join(self._format_history_match(match) for match in self.history_matches)
        return f"DUPLICATES AGAINST ALREADY-INDEXED REPO HISTORY:\n\n{entries}"

    def _format_history_match(self, history_match: ChunkHistoryMatch) -> str:
        """Renders one chunk from this file, plus everything it duplicates."""
        own = history_match.chunk
        own_snippet = _extract_snippet(self.file_content, own)
        lines = [f"Chunk {_format_location(own)} in this file:", _format_snippet(own_snippet)]
        lines += self._format_structural_matches(history_match.structural_matches)
        lines += self._format_semantic_matches(history_match.semantic_matches)
        return "\n".join(lines)

    def _format_structural_matches(self, matches: list[StructuralMatch]) -> list[str]:
        """Renders exact-clone matches: location only, no code available."""
        if not matches:
            return []
        return ["Exact structural matches already indexed:"] + [f"- {_format_location(match)}" for match in matches]

    def _format_semantic_matches(self, matches: list[SimilarChunk]) -> list[str]:
        """Renders similar-behavior matches: location, code, and similarity score."""
        if not matches:
            return []
        header = ["Similar-behavior matches already indexed (not exact clones):"]
        entries = [
            f"- {_format_location(match, f'similarity={match.score:.2f}')}\n{_format_snippet(match.code)}"
            for match in matches
        ]
        return header + entries
