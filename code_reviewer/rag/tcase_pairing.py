"""
    Retrieves candidate test files for one source file from a repo's indexed
    corpus, through two buckets: a deterministic naming-convention match and
    a semantic search. Deciding which candidates are real is not this
    module's job — see tcase_pairing_retry.py.
"""
import re
from dataclasses import dataclass
from typing import Protocol

from code_reviewer.pipeline.code_splitter.errors import CodeChunkingError
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.pipeline.pairing_stem import pairing_stem
from code_reviewer.pipeline.pr_file_selection import is_test_file
from code_reviewer.rag.code_similarity_index import CodeSimilarityIndex
from code_reviewer.rag.indexer import FileChunk, LlamaIndexRagManager
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.submission import SubmittedFile

DETERMINISTIC_CANDIDATE_CAP = 3
SEMANTIC_TOP_K = 10
SEMANTIC_FUSION_CAP = 10
_RRF_K = 60


@dataclass(frozen=True)
class PairingCandidate:
    file_path: str
    content: str


@dataclass(frozen=True)
class PairingBuckets:
    deterministic: list[PairingCandidate]
    semantic: list[PairingCandidate]


@dataclass(frozen=True)
class PairingEvidenceSources:
    embedding_index: LlamaIndexRagManager
    code_similarity_index: CodeSimilarityIndex


class PairingCandidateFinder:
    """Finds files in a repo's indexed corpus that may be tests of a source file."""

    def __init__(self, evidence_sources: PairingEvidenceSources) -> None:
        self._sources = evidence_sources

    def find_candidates(
        self, repo_data: RepoData, source_file: SubmittedFile, semantic_query: str | None = None
    ) -> PairingBuckets:
        """Only ever returns test files, never source_file itself.

        Args:
            semantic_query: A natural-language query replacing the default
                search derived from source_file's code; the deterministic
                bucket ignores it.

        Raises:
            VectorStoreQueryError: If a corpus lookup fails.
            ChunkExplanationError: If explaining source_file's code fails.
        """
        deterministic_paths = self._deterministic_paths(repo_data, source_file.file_path)
        semantic_paths = self._semantic_paths(repo_data, source_file, semantic_query)
        semantic_only_paths = [path for path in semantic_paths if path not in deterministic_paths]
        symbols = _source_symbols(source_file.content)
        return PairingBuckets(
            deterministic=self._as_candidates(repo_data, deterministic_paths, symbols),
            semantic=self._as_candidates(repo_data, semantic_only_paths, symbols),
        )

    def _deterministic_paths(self, repo_data: RepoData, source_path: str) -> list[str]:
        indexed_paths = self._sources.embedding_index.list_indexed_file_paths(repo_data.repo_id, repo_data.owner_id)
        source_stem = pairing_stem(source_path)
        matches = [
            path for path in indexed_paths
            if _is_other_test_file(path, source_path) and pairing_stem(path) == source_stem
        ]
        return matches[:DETERMINISTIC_CANDIDATE_CAP]

    def _semantic_paths(self, repo_data: RepoData, source_file: SubmittedFile, semantic_query: str | None) -> list[str]:
        embedding_index = self._sources.embedding_index
        if semantic_query is None:
            dense_matches = embedding_index.find_similar(repo_data, source_file.content, top_k=SEMANTIC_TOP_K)
        else:
            dense_matches = embedding_index.find_similar_by_query(repo_data, semantic_query, top_k=SEMANTIC_TOP_K)
        lexical_query = semantic_query or source_file.content
        lexical_matches = self._sources.code_similarity_index.find_lexical_matches(
            repo_data, lexical_query, top_k=SEMANTIC_TOP_K
        )
        dense_paths = _valid_test_file_paths(dense_matches, source_file.file_path)
        lexical_paths = _valid_test_file_paths(lexical_matches, source_file.file_path)
        fused = _reciprocal_rank_fusion([dense_paths, lexical_paths])
        return fused[:SEMANTIC_FUSION_CAP]

    def _as_candidates(
        self, repo_data: RepoData, file_paths: list[str], symbols: frozenset[str]
    ) -> list[PairingCandidate]:
        return [
            PairingCandidate(file_path=path, content=self._file_content(repo_data, path, symbols))
            for path in file_paths
        ]

    def _file_content(self, repo_data: RepoData, file_path: str, symbols: frozenset[str]) -> str:
        chunks = self._sources.embedding_index.get_file_chunks(repo_data.repo_id, repo_data.owner_id, file_path)
        relevant = _relevant_chunks(chunks, symbols)
        return "\n".join(chunk.code for chunk in sorted(relevant, key=lambda chunk: chunk.start_line))


class _RankedMatch(Protocol):
    file_path: str


def _is_other_test_file(path: str, source_path: str) -> bool:
    return path != source_path and is_test_file(path)


def _valid_test_file_paths(matches: list[_RankedMatch], source_path: str) -> list[str]:
    unique_paths = dict.fromkeys(match.file_path for match in matches if _is_other_test_file(match.file_path, source_path))
    return list(unique_paths)


def _reciprocal_rank_fusion(ranked_path_lists: list[list[str]]) -> list[str]:
    """Merges independently ranked path lists into one ranking, weighting a
    path by 1/(k+rank) summed across every list it appears in — a path
    ranked highly by more than one retrieval method scores higher than one
    only a single method found. Score scale is not comparable across dense
    and BM25 results, so fusing by rank position, not raw score, is what
    makes combining them meaningful at all."""
    scores: dict[str, float] = {}
    for ranked_paths in ranked_path_lists:
        for rank, path in enumerate(ranked_paths, start=1):
            scores[path] = scores.get(path, 0.0) + 1 / (_RRF_K + rank)
    return sorted(scores, key=lambda path: scores[path], reverse=True)


def _source_symbols(source_code: str) -> frozenset[str]:
    try:
        chunks = PythonCodeSplit().split_code(source_code)
    except CodeChunkingError:
        return frozenset()
    return frozenset(chunk.name for chunk in chunks)


def _relevant_chunks(chunks: list[FileChunk], symbols: frozenset[str]) -> list[FileChunk]:
    if not symbols:
        return chunks
    matching = [chunk for chunk in chunks if _mentions_any_symbol(chunk.code, symbols)]
    return matching or chunks


def _mentions_any_symbol(code: str, symbols: frozenset[str]) -> bool:
    return any(re.search(rf"\b{re.escape(symbol)}\b", code) for symbol in symbols)
