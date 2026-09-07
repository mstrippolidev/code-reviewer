"""
    Tests for HistoryMatchReranker's own logic: candidates are ranked
    jointly across all three buckets and only the top max_candidates
    overall survive — never per-bucket, and never by an absolute score
    threshold — against a fake postprocessor, never a real cross-encoder.
    The real model is exercised separately in test_dry_matching.py's
    integration section.
"""
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralMatch

QUERY_CODE = "def total(values):\n    return sum(values)\n"


class _FakePostprocessor:
    """Stands in for the cross-encoder: scores each node by its position
    within its own bucket (from a per-bucket score list), and records the
    query text it saw."""

    def __init__(self, scores: dict[str, list[float]] | None = None, error: bool = False) -> None:
        self._scores = scores or {}
        self._error = error
        self.received_query: str | None = None

    def postprocess_nodes(self, nodes, query_bundle=None):
        if self._error:
            raise RuntimeError("cross-encoder unavailable")
        self.received_query = query_bundle.query_str if query_bundle else None
        for node in nodes:
            bucket = node.node.metadata["bucket"]
            index = node.node.metadata["candidate_index"]
            bucket_scores = self._scores.get(bucket, [1.0] * (index + 1))
            node.score = bucket_scores[index]
        return nodes


def _semantic_match(file_path: str = "legacy/totals.py", code: str = "def total(v):\n    return sum(v)\n") -> SimilarChunk:
    return SimilarChunk(file_path=file_path, chunk_name="total", start_line=1, end_line=2, text="sums a list", score=0.9, code=code)


def _code_match(file_path: str = "legacy/other.py", code: str = "def total(v):\n    return sum(v)\n") -> CodeMatch:
    return CodeMatch(file_path=file_path, chunk_name="total", start_line=1, end_line=2, code=code, score=0.8)


def _lexical_match(file_path: str = "legacy/third.py", code: str = "def total(v):\n    return sum(v)\n") -> LexicalMatch:
    return LexicalMatch(file_path=file_path, chunk_name="total", start_line=1, end_line=2, code=code, score=3.0)


def _match(**buckets) -> ChunkHistoryMatch:
    return ChunkHistoryMatch(
        chunk=StructuralMatch(file_path="a.py", chunk_name="total", start_line=1, end_line=2),
        structural_matches=buckets.get("structural_matches", []),
        semantic_matches=buckets.get("semantic_matches", []),
        code_matches=buckets.get("code_matches", []),
        lexical_matches=buckets.get("lexical_matches", []),
    )


def test_structural_matches_are_never_sent_to_the_postprocessor() -> None:
    """Verify an exact structural match passes through untouched — no
    relevance score to confirm on an already-certain clone."""
    structural = [StructuralMatch(file_path="legacy/math_ops.py", chunk_name="total", start_line=1, end_line=2)]
    match = _match(structural_matches=structural)
    reranker = HistoryMatchReranker(max_candidates=5, postprocessor=_FakePostprocessor())

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.structural_matches == structural


def test_top_ranked_candidates_survive_up_to_max_candidates() -> None:
    strong = _semantic_match(file_path="legacy/strong.py")
    middle = _semantic_match(file_path="legacy/middle.py")
    weak = _semantic_match(file_path="legacy/weak.py")
    match = _match(semantic_matches=[strong, middle, weak])
    postprocessor = _FakePostprocessor(scores={"semantic_matches": [0.9, 0.5, 0.1]})
    reranker = HistoryMatchReranker(max_candidates=2, postprocessor=postprocessor)

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == [strong, middle]


def test_candidates_compete_across_buckets_rather_than_within_them() -> None:
    """A weak candidate from one bucket must not survive just because it
    was the strongest thing in its own bucket — every bucket's candidates
    are ranked together against the same overall cutoff."""
    strong_semantic = _semantic_match(file_path="legacy/strong.py")
    weak_semantic = _semantic_match(file_path="legacy/weak.py")
    strong_code = _code_match(file_path="legacy/other.py")
    match = _match(semantic_matches=[strong_semantic, weak_semantic], code_matches=[strong_code])
    postprocessor = _FakePostprocessor(scores={"semantic_matches": [0.9, 0.1], "code_matches": [0.5]})
    reranker = HistoryMatchReranker(max_candidates=2, postprocessor=postprocessor)

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == [strong_semantic]
    assert reranked.code_matches == [strong_code]


def test_no_candidates_in_any_bucket_never_calls_the_postprocessor() -> None:
    match = _match()
    postprocessor = _FakePostprocessor()
    reranker = HistoryMatchReranker(max_candidates=5, postprocessor=postprocessor)

    reranker.rerank(QUERY_CODE, match)

    assert postprocessor.received_query is None


def test_postprocessor_failure_falls_back_to_every_buckets_unranked_candidates() -> None:
    """Verify a cross-encoder failure degrades to unranked evidence rather
    than silently dropping real duplicate evidence."""
    semantic_candidates = [_semantic_match()]
    code_candidates = [_code_match()]
    match = _match(semantic_matches=semantic_candidates, code_matches=code_candidates)
    reranker = HistoryMatchReranker(max_candidates=5, postprocessor=_FakePostprocessor(error=True))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == semantic_candidates
    assert reranked.code_matches == code_candidates


def test_query_sent_to_the_postprocessor_is_the_chunks_own_code() -> None:
    match = _match(lexical_matches=[_lexical_match()])
    postprocessor = _FakePostprocessor()
    reranker = HistoryMatchReranker(max_candidates=5, postprocessor=postprocessor)

    reranker.rerank(QUERY_CODE, match)

    assert postprocessor.received_query == QUERY_CODE
