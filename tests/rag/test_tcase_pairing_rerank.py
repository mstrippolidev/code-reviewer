"""
    Tests for PairingReranker's own logic against a fake postprocessor,
    never a real cross-encoder.
"""
from code_reviewer.rag.tcase_pairing import PairingBuckets, PairingCandidate
from code_reviewer.rag.tcase_pairing_rerank import PairingReranker


class FakePostprocessor:
    """Scores each candidate from a content-to-score map, recording the query it saw."""

    def __init__(self, scores: dict[str, float] | None = None, error: bool = False) -> None:
        self._scores = scores or {}
        self._error = error
        self.received_query: str | None = None

    def postprocess_nodes(self, nodes, query_bundle=None):
        if self._error:
            raise RuntimeError("cross-encoder unavailable")
        self.received_query = query_bundle.query_str
        for node in nodes:
            node.score = self._scores.get(node.node.get_content(), 0.0)
        return nodes


def _candidate(name: str) -> PairingCandidate:
    return PairingCandidate(file_path=f"tests/{name}.py", content=name)


def test_candidates_from_both_buckets_compete_on_one_ranking() -> None:
    """Verify a semantic candidate can outrank a deterministic one."""
    buckets = PairingBuckets(deterministic=[_candidate("named")], semantic=[_candidate("found")])
    reranker = PairingReranker(max_candidates=5, postprocessor=FakePostprocessor({"named": 1.0, "found": 5.0}))

    ranked = reranker.rerank("query", buckets)

    assert [candidate.content for candidate in ranked] == ["found", "named"]


def test_only_the_top_max_candidates_survive() -> None:
    """Verify the judge never sees more than max_candidates files."""
    buckets = PairingBuckets(deterministic=[], semantic=[_candidate("low"), _candidate("high"), _candidate("mid")])
    postprocessor = FakePostprocessor({"low": 1.0, "high": 3.0, "mid": 2.0})

    ranked = PairingReranker(max_candidates=2, postprocessor=postprocessor).rerank("query", buckets)

    assert [candidate.content for candidate in ranked] == ["high", "mid"]


def test_scoring_failure_keeps_candidates_in_bucket_order_capped() -> None:
    """Verify a cross-encoder outage degrades to unranked candidates rather than losing them."""
    buckets = PairingBuckets(deterministic=[_candidate("named")], semantic=[_candidate("a"), _candidate("b")])
    reranker = PairingReranker(max_candidates=2, postprocessor=FakePostprocessor(error=True))

    ranked = reranker.rerank("query", buckets)

    assert [candidate.content for candidate in ranked] == ["named", "a"]


def test_empty_buckets_never_call_the_cross_encoder() -> None:
    """Verify nothing is scored when no candidate was found."""
    postprocessor = FakePostprocessor()

    PairingReranker(max_candidates=5, postprocessor=postprocessor).rerank("query", PairingBuckets([], []))

    assert postprocessor.received_query is None


def test_candidates_are_scored_against_the_given_query() -> None:
    """Verify a retry ranks against its rewritten query, not the original source."""
    postprocessor = FakePostprocessor()
    buckets = PairingBuckets(deterministic=[_candidate("named")], semantic=[])

    PairingReranker(max_candidates=5, postprocessor=postprocessor).rerank("rewritten query", buckets)

    assert postprocessor.received_query == "rewritten query"
