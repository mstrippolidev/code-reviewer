from code_reviewer.rag.dry_clustering import cluster_history_matches, location_key
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.structural_hash_store import StructuralMatch


def _chunk(file_path: str, chunk_name: str, start_line: int = 1, end_line: int = 5) -> StructuralMatch:
    return StructuralMatch(file_path=file_path, chunk_name=chunk_name, start_line=start_line, end_line=end_line)


def _semantic_match(file_path: str, chunk_name: str, start_line: int = 1, end_line: int = 5) -> SimilarChunk:
    return SimilarChunk(
        file_path=file_path, chunk_name=chunk_name, start_line=start_line, end_line=end_line,
        text="t", score=0.9, code=f"def {chunk_name}(): ...",
    )


def _history_match(chunk: StructuralMatch, *semantic_matches: SimilarChunk) -> ChunkHistoryMatch:
    return ChunkHistoryMatch(chunk=chunk, structural_matches=[], semantic_matches=list(semantic_matches))


def test_chunk_with_no_fuzzy_matches_maps_to_an_empty_cluster() -> None:
    match = _history_match(_chunk("handlers.py", "bad_request"))

    clusters = cluster_history_matches([match])

    assert clusters[location_key(match.chunk)] == []


def test_two_chunks_that_find_each_other_are_pooled_together() -> None:
    chunk_a = _chunk("handlers.py", "bad_request")
    chunk_b = _chunk("handlers.py", "not_found")
    match_a = _history_match(chunk_a, _semantic_match("handlers.py", "not_found"))
    match_b = _history_match(chunk_b, _semantic_match("handlers.py", "bad_request"))

    clusters = cluster_history_matches([match_a, match_b])

    assert [located.location for located in clusters[location_key(chunk_a)]] == [chunk_b]


def test_transitively_connected_chunks_pool_the_full_cluster() -> None:
    chunk_a = _chunk("handlers.py", "bad_request")
    chunk_b = _chunk("handlers.py", "not_found")
    chunk_c = _chunk("handlers.py", "conflict")
    match_a = _history_match(chunk_a, _semantic_match("handlers.py", "not_found"))
    match_b = _history_match(chunk_b, _semantic_match("handlers.py", "conflict"))
    match_c = _history_match(chunk_c)

    clusters = cluster_history_matches([match_a, match_b, match_c])

    pooled_locations = [located.location for located in clusters[location_key(chunk_a)]]
    assert chunk_c in pooled_locations


def test_unrelated_chunks_stay_in_separate_clusters() -> None:
    chunk_a = _chunk("handlers.py", "bad_request")
    chunk_b = _chunk("other.py", "unrelated")
    match_a = _history_match(chunk_a, _semantic_match("legacy/aggregates.py", "total"))
    match_b = _history_match(chunk_b, _semantic_match("legacy/text.py", "slugify"))

    clusters = cluster_history_matches([match_a, match_b])

    pooled_locations_for_a = [located.location for located in clusters[location_key(chunk_a)]]
    assert chunk_b not in pooled_locations_for_a


def test_sibling_query_chunk_in_a_cluster_carries_no_resolved_code() -> None:
    chunk_a = _chunk("handlers.py", "bad_request")
    chunk_b = _chunk("handlers.py", "not_found")
    match_a = _history_match(chunk_a, _semantic_match("handlers.py", "not_found"))
    match_b = _history_match(chunk_b)

    clusters = cluster_history_matches([match_a, match_b])

    sibling = next(located for located in clusters[location_key(chunk_a)] if located.location == chunk_b)
    assert sibling.code is None


def test_external_candidate_in_a_cluster_carries_its_own_code() -> None:
    chunk_a = _chunk("handlers.py", "bad_request")
    match_a = _history_match(chunk_a, _semantic_match("legacy/aggregates.py", "total"))

    clusters = cluster_history_matches([match_a])

    external = clusters[location_key(chunk_a)][0]
    assert external.code == "def total(): ..."
