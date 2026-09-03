"""
    Tests for HistoryMatchReranker's own logic: which buckets get scored,
    how the score floor is applied, and how a scoring failure degrades —
    all against a fake postprocessor, never a real cross-encoder. The real
    model is exercised separately in test_dry_matching.py's integration
    section.
"""
from code_reviewer.rag.code_similarity_index import CodeMatch, LexicalMatch
from code_reviewer.rag.dry_matching import ChunkHistoryMatch
from code_reviewer.rag.indexer import SimilarChunk
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.structural_hash_store import StructuralMatch

QUERY_CODE = "def total(values):\n    return sum(values)\n"


class _FakePostprocessor:
    """Stands in for the cross-encoder: assigns each candidate a score by
    its position in the input list, and records the query text it saw."""

    def __init__(self, scores: list[float] | None = None, error: bool = False) -> None:
        self._scores = scores
        self._error = error
        self.received_query: str | None = None

    def postprocess_nodes(self, nodes, query_bundle=None):
        if self._error:
            raise RuntimeError("cross-encoder unavailable")
        self.received_query = query_bundle.query_str if query_bundle else None
        scores = self._scores if self._scores is not None else [1.0] * len(nodes)
        for node in nodes:
            node.score = scores[node.node.metadata["candidate_index"]]
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
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.structural_matches == structural


def test_candidate_scoring_above_the_floor_survives() -> None:
    match = _match(semantic_matches=[_semantic_match()])
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[0.9]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == match.semantic_matches


def test_candidate_scoring_exactly_at_the_floor_survives() -> None:
    """Verify the floor is inclusive, not a strict greater-than."""
    match = _match(semantic_matches=[_semantic_match()])
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[0.5]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == match.semantic_matches


def test_candidate_scoring_below_the_floor_is_dropped() -> None:
    match = _match(semantic_matches=[_semantic_match()])
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[0.49]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == []


def test_only_the_survivor_is_kept_when_a_bucket_has_a_strong_and_a_weak_candidate() -> None:
    strong = _semantic_match(file_path="legacy/strong.py")
    weak = _semantic_match(file_path="legacy/weak.py")
    match = _match(semantic_matches=[strong, weak])
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[0.9, 0.1]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == [strong]


def test_empty_bucket_never_calls_the_postprocessor() -> None:
    match = _match()
    postprocessor = _FakePostprocessor()
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=postprocessor)

    reranker.rerank(QUERY_CODE, match)

    assert postprocessor.received_query is None


def test_postprocessor_failure_falls_back_to_the_unranked_candidates() -> None:
    """Verify a cross-encoder failure degrades to unranked evidence rather
    than silently dropping real duplicate evidence."""
    candidates = [_code_match()]
    match = _match(code_matches=candidates)
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(error=True))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.code_matches == candidates


def test_query_sent_to_the_postprocessor_is_the_chunks_own_code() -> None:
    match = _match(lexical_matches=[_lexical_match()])
    postprocessor = _FakePostprocessor()
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=postprocessor)

    reranker.rerank(QUERY_CODE, match)

    assert postprocessor.received_query == QUERY_CODE


def test_each_bucket_is_reranked_independently() -> None:
    """Verify a low score in one bucket doesn't affect another bucket's
    own candidates."""
    match = _match(semantic_matches=[_semantic_match()], code_matches=[_code_match()], lexical_matches=[_lexical_match()])
    reranker = HistoryMatchReranker(score_floor=0.5, postprocessor=_FakePostprocessor(scores=[0.9]))

    reranked = reranker.rerank(QUERY_CODE, match)

    assert reranked.semantic_matches == match.semantic_matches
    assert reranked.code_matches == match.code_matches
    assert reranked.lexical_matches == match.lexical_matches
