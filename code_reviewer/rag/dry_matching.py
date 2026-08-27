"""
    Structural clone matching for DRY: exact structural-hash duplicates,
    both across a PR's own files and against a repo's indexed history.
"""
from dataclasses import dataclass

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash import compute_structural_hash
from code_reviewer.rag.structural_hash_store import StructuralHashStore, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile


def find_intra_pr_duplicates(files: list[SubmittedFile]) -> list[list[StructuralMatch]]:
    """
    Returns:
        One group per structural hash shared by 2+ chunks, each group
        listing every location (file, chunk, lines) that shares it.

    Raises:
        DryMatchingChunkingError: If any file cannot be split into chunks.
    """
    chunks_by_hash = _group_pr_chunks_by_hash(files)
    return [locations for locations in chunks_by_hash.values() if len(locations) > 1]


def _group_pr_chunks_by_hash(files: list[SubmittedFile]) -> dict[str, list[StructuralMatch]]:
    chunks_by_hash: dict[str, list[StructuralMatch]] = {}
    for file in files:
        for chunk in _split_file(file.file_path, file.content):
            structural_hash = compute_structural_hash(chunk.code)
            chunks_by_hash.setdefault(structural_hash, []).append(_as_match(file.file_path, chunk))
    return chunks_by_hash


@dataclass
class ChunkHistoryMatch:
    """One of this file's own chunks, paired with the indexed history locations that structurally duplicate it."""

    chunk: StructuralMatch
    history_matches: list[StructuralMatch]


class CrossHistoryDuplicateFinder:
    """Finds a file's chunks that structurally duplicate content already indexed in the repo's history."""

    def __init__(self, structural_hash_store: StructuralHashStore, repo_data: RepoData) -> None:
        self._structural_hash_store = structural_hash_store
        self._repo_data = repo_data

    def find(self, file_path: str, content: str) -> list[ChunkHistoryMatch]:
        """
        Raises:
            DryMatchingChunkingError: If content cannot be split into chunks.
        """
        return [
            match
            for chunk in _split_file(file_path, content)
            if (match := self._match_for_chunk(file_path, chunk)) is not None
        ]

    def _match_for_chunk(self, file_path: str, chunk: CodeChunk) -> ChunkHistoryMatch | None:
        chunk_location = _as_match(file_path, chunk)
        structural_hash = compute_structural_hash(chunk.code)
        history_matches = self._structural_hash_store.find_by_hash(
            self._repo_data.repo_id, self._repo_data.owner_id, structural_hash
        )
        other_matches = _exclude_self_match(history_matches, chunk_location)
        if not other_matches:
            return None
        return ChunkHistoryMatch(chunk=chunk_location, history_matches=other_matches)


def _exclude_self_match(matches: list[StructuralMatch], chunk_location: StructuralMatch) -> list[StructuralMatch]:
    return [
        match
        for match in matches
        if not (match.file_path == chunk_location.file_path and match.chunk_name == chunk_location.chunk_name)
    ]


def _as_match(file_path: str, chunk: CodeChunk) -> StructuralMatch:
    return StructuralMatch(
        file_path=file_path, chunk_name=chunk.name, start_line=chunk.start_line, end_line=chunk.end_line
    )


def _split_file(file_path: str, content: str) -> list[CodeChunk]:
    try:
        return PythonCodeSplit().split_code(content)
    except CodeChunkingError as error:
        raise DryMatchingChunkingError(f"Could not chunk {file_path!r} for structural duplicate matching.") from error
