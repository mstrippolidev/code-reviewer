"""
    Groups DRY's per-chunk fuzzy candidates into clusters of mutually
    similar locations.
"""
from dataclasses import dataclass
from typing import Protocol

from code_reviewer.rag.disjoint_set import DisjointSet
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.structural_hash_store import StructuralMatch

LocationKey = tuple[str, str, int, int]


class _FuzzyCandidate(Protocol):
    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    code: str


@dataclass(frozen=True)
class ClusterLocation:
    """code is None when the location is one of this file's own chunks —
    the caller resolves it from file_content instead."""

    location: StructuralMatch
    code: str | None


def cluster_history_matches(history_matches: list[ChunkHistoryMatch]) -> dict[LocationKey, list[ClusterLocation]]:
    """Maps each own chunk's key to every other location transitively
    connected to it through any bucket's fuzzy candidates."""
    disjoint_set: DisjointSet[LocationKey] = DisjointSet()
    known_locations = _index_known_locations(history_matches, disjoint_set)
    clusters_by_root = _group_by_root(known_locations, disjoint_set)
    return {
        own_key: [known_locations[key] for key in clusters_by_root[disjoint_set.find(own_key)] if key != own_key]
        for own_key in (location_key(match.chunk) for match in history_matches)
    }


def _index_known_locations(
    history_matches: list[ChunkHistoryMatch], disjoint_set: DisjointSet[LocationKey]
) -> dict[LocationKey, ClusterLocation]:
    # Own chunks are registered first, unconditionally, so one being
    # rediscovered as someone else's candidate never shadows it with a
    # possibly-stale indexed code copy — setdefault below then always
    # loses to this for an own chunk, regardless of iteration order.
    known_locations: dict[LocationKey, ClusterLocation] = {
        location_key(match.chunk): ClusterLocation(match.chunk, code=None) for match in history_matches
    }
    for match in history_matches:
        own_key = location_key(match.chunk)
        for candidate in _fuzzy_candidates(match):
            candidate_key = location_key(candidate)
            known_locations.setdefault(candidate_key, ClusterLocation(_as_structural_match(candidate), candidate.code))
            disjoint_set.union(own_key, candidate_key)
    return known_locations


def _group_by_root(
    known_locations: dict[LocationKey, ClusterLocation], disjoint_set: DisjointSet[LocationKey]
) -> dict[LocationKey, list[LocationKey]]:
    clusters_by_root: dict[LocationKey, list[LocationKey]] = {}
    for key in known_locations:
        clusters_by_root.setdefault(disjoint_set.find(key), []).append(key)
    return clusters_by_root


def _fuzzy_candidates(match: ChunkHistoryMatch) -> list[_FuzzyCandidate]:
    return [*match.semantic_matches, *match.code_matches, *match.lexical_matches]


def location_key(location: _FuzzyCandidate | StructuralMatch) -> LocationKey:
    return (location.file_path, location.chunk_name, location.start_line, location.end_line)


def _as_structural_match(candidate: _FuzzyCandidate) -> StructuralMatch:
    return StructuralMatch(
        file_path=candidate.file_path,
        chunk_name=candidate.chunk_name,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
    )
