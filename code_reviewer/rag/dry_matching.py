"""
    DRY's duplicate-detection facade. This module is the only place that
    knows how to turn "a file changed in this PR" into per-chunk duplicate
    evidence — it composes lower-level rag/ primitives that know nothing
    about DRY, PRs, or files: StructuralHashStore's exact structural-hash
    lookup (Type 1-3 clones), LlamaIndexRagManager's explanation-embedding
    search (Type-4 clones whose auto-generated summaries converge), and
    CodeSimilarityIndex's two routes over the same stored code — dense
    (catches Type-4 near-misses whose summaries diverged instead) and BM25
    (catches copy-paste-with-edits via shared identifiers/calls). All four
    buckets are recall devices, unioned rather than score-fused: nothing
    here decides which candidate is a real duplicate, that is the
    downstream re-ranker and judge's job. agents/dry.py (not yet built) is
    the intended caller of this module's public functions.
"""
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.interface import CodeChunk
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.rag.code_similarity_index import CodeMatch, CodeSimilarityIndex, LexicalMatch
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.indexer import LlamaIndexRagManager, SimilarChunk
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash import compute_structural_hash
from code_reviewer.rag.structural_hash_store import StructuralHashStore, StructuralMatch
from code_reviewer.schemas.submission import SubmittedFile

SEMANTIC_MATCH_TOP_K = 3
CODE_MATCH_TOP_K = 3
LEXICAL_MATCH_TOP_K = 3


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
    locations that duplicate it. Each bucket is kept separate since its
    confidence differs: a structural match is an exact clone; the other
    three are similarity candidates found by different signals (LLM
    explanation, raw code, shared vocabulary) and are never fused into one
    score — a candidate several buckets agree on is stronger evidence than
    one bucket alone, which only a re-ranker downstream can tell apart.
    """

    chunk: StructuralMatch
    structural_matches: list[StructuralMatch]
    semantic_matches: list[SimilarChunk]
    code_matches: list[CodeMatch] = field(default_factory=list)
    lexical_matches: list[LexicalMatch] = field(default_factory=list)


class _NamedChunkLocation(Protocol):
    """Contract shared by every match type: enough to tell whether a match
    is the chunk's own previously-indexed self."""

    file_path: str
    chunk_name: str


_NamedChunkLocationT = TypeVar("_NamedChunkLocationT", bound=_NamedChunkLocation)


@dataclass
class DuplicateEvidenceSources:
    """Bundles every store CrossHistoryDuplicateFinder queries, so adding
    another recall bucket never grows its constructor past the project's
    3-parameter limit (the same pattern ExemplarCorpora uses for COUP)."""

    structural_hash_store: StructuralHashStore
    embedding_index: LlamaIndexRagManager
    code_similarity_index: CodeSimilarityIndex


class CrossHistoryDuplicateFinder:
    """Finds a file's chunks that duplicate content already indexed in the
    repo's history, across four independent recall signals: exact
    structural hash, explanation-embedding similarity, raw-code embedding
    similarity, and BM25 keyword overlap.
    """

    def __init__(self, evidence_sources: DuplicateEvidenceSources, repo_data: RepoData) -> None:
        self._sources = evidence_sources
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
        code_matches = self._code_matches(chunk_location, chunk)
        lexical_matches = self._lexical_matches(chunk_location, chunk)
        if not any([structural_matches, semantic_matches, code_matches, lexical_matches]):
            return None
        return ChunkHistoryMatch(
            chunk=chunk_location,
            structural_matches=structural_matches,
            semantic_matches=semantic_matches,
            code_matches=code_matches,
            lexical_matches=lexical_matches,
        )

    def _structural_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[StructuralMatch]:
        structural_hash = compute_structural_hash(chunk.code)
        matches = self._sources.structural_hash_store.find_by_hash(
            self._repo_data.repo_id, self._repo_data.owner_id, structural_hash
        )
        return _exclude_self_match(matches, chunk_location)

    def _semantic_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[SimilarChunk]:
        matches = self._sources.embedding_index.find_similar(self._repo_data, chunk.code, top_k=SEMANTIC_MATCH_TOP_K)
        return _exclude_self_match(matches, chunk_location)

    def _code_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[CodeMatch]:
        matches = self._sources.code_similarity_index.find_similar(self._repo_data, chunk.code, top_k=CODE_MATCH_TOP_K)
        return _exclude_self_match(matches, chunk_location)

    def _lexical_matches(self, chunk_location: StructuralMatch, chunk: CodeChunk) -> list[LexicalMatch]:
        matches = self._sources.code_similarity_index.find_lexical_matches(
            self._repo_data, chunk.code, top_k=LEXICAL_MATCH_TOP_K
        )
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
