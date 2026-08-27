"""
    DRY's duplicate-detection facade. This module is the only place that
    knows how to turn "a file changed in this PR" into per-chunk duplicate
    evidence — it composes two lower-level rag/ primitives that know nothing
    about DRY, PRs, or files: StructuralHashStore's exact structural-hash
    lookup (Type 1-3 clones) and LlamaIndexRagManager's embedding-similarity
    search (Type-4 clones). agents/dry.py (not yet built) is the intended
    caller of this module's public functions.
"""
from dataclasses import dataclass
from typing import Protocol, TypeVar

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.indexer import LlamaIndexRagManager, SimilarChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash import compute_structural_hash
from code_reviewer.rag.structural_hash_store import StructuralHashStore, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile

SEMANTIC_MATCH_TOP_K = 3


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
    """One of this file's own chunks, paired with the indexed-history
    locations that duplicate it. Structural and semantic matches are kept
    separate since their confidence differs: a structural match is an exact
    clone, a semantic match is only a similarity candidate.
    """

    chunk: StructuralMatch
    structural_matches: list[StructuralMatch]
    semantic_matches: list[SimilarChunk]


class _NamedChunkLocation(Protocol):
    """Contract shared by StructuralMatch and SimilarChunk: enough to tell
    whether a match is the chunk's own previously-indexed self."""

    file_path: str
    chunk_name: str


_NamedChunkLocationT = TypeVar("_NamedChunkLocationT", bound=_NamedChunkLocation)


class CrossHistoryDuplicateFinder:
    """Finds a file's chunks that duplicate content already indexed in the
    repo's history, by exact structural hash and by semantic similarity.
    """

    def __init__(
        self,
        structural_hash_store: StructuralHashStore,
        embedding_index: LlamaIndexRagManager,
        repo_data: RepoData,
    ) -> None:
        self._structural_hash_store = structural_hash_store
        self._embedding_index = embedding_index
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
        structural_matches = self._structural_matches(chunk_location, chunk)
        semantic_matches = self._semantic_matches(chunk_location, chunk)
        if not structural_matches and not semantic_matches:
            return None
        return ChunkHistoryMatch(
            chunk=chunk_location, structural_matches=structural_matches, semantic_matches=semantic_matches
        )

    def _structural_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[StructuralMatch]:
        structural_hash = compute_structural_hash(chunk.code)
        matches = self._structural_hash_store.find_by_hash(
            self._repo_data.repo_id, self._repo_data.owner_id, structural_hash
        )
        return _exclude_self_match(matches, chunk_location)

    def _semantic_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[SimilarChunk]:
        matches = self._embedding_index.find_similar(self._repo_data, chunk.code, top_k=SEMANTIC_MATCH_TOP_K)
        return _exclude_self_match(matches, chunk_location)


def _exclude_self_match(
    matches: list[_NamedChunkLocationT], chunk_location: StructuralMatch
) -> list[_NamedChunkLocationT]:
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
