"""
    Cross-encoder sorting pass over dry_matching.py's over-fetched
    similarity buckets, before DRY's evidence ever reaches an LLM. A
    bi-encoder must commit to one representation per corpus, since both
    sides of the comparison share one vector space — explanation for the
    semantic bucket, raw code for the code and lexical buckets. A
    cross-encoder scores a pair jointly and needs no shared space, so every
    candidate's own code (already carried by every match type) can be
    scored here regardless of which representation retrieved it.

    Selection is by rank across every bucket combined (top max_candidates
    overall), not by an absolute score threshold: this model's raw score is
    only meaningful relative to other candidates scored against the same
    query, not as a fixed cutoff — the same genuine duplicate that scores
    clearly positive against a short query can score deeply negative once
    the query is a large chunk with a lot of unrelated surrounding code,
    even though it still ranks above every actually-unrelated candidate.
    Rejecting a candidate that makes the cut is DryJudge's job, not this
    pass's — this pass only decides which candidates are worth asking
    about at all.

    structural_matches are untouched: an exact structural-hash match is
    already a certain clone, nothing for a relevance score to confirm.
"""
import logging
from typing import Protocol

from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from code_reviewer.rag.dry_matching import ChunkHistoryMatch

logger = logging.getLogger(__name__)

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATE_CAP = 30

_BUCKET_FIELDS = ("semantic_matches", "code_matches", "lexical_matches")


class _ScoredCode(Protocol):
    code: str


class _NodePostprocessor(Protocol):
    def postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]: ...


class HistoryMatchReranker:
    """Re-scores one chunk's similarity-candidate buckets (semantic,
    raw-code, lexical) jointly, keeping only the top max_candidates most
    relevant candidates overall — a real duplicate found by, say, the
    lexical bucket is no more or less real than one found by the semantic
    bucket, so they compete on the same ranking rather than each bucket
    getting its own independent allowance."""

    def __init__(self, max_candidates: int, postprocessor: _NodePostprocessor | None = None) -> None:
        self._max_candidates = max_candidates
        self._postprocessor = postprocessor or SentenceTransformerRerank(
            model=CROSS_ENCODER_MODEL, top_n=RERANK_CANDIDATE_CAP
        )

    def rerank(self, query_code: str, match: ChunkHistoryMatch) -> ChunkHistoryMatch:
        buckets = {field: getattr(match, field) for field in _BUCKET_FIELDS}
        survivors = self._top_candidates(QueryBundle(query_str=query_code), buckets)
        return ChunkHistoryMatch(chunk=match.chunk, structural_matches=match.structural_matches, **survivors)

    def _top_candidates(
        self, query: QueryBundle, buckets: dict[str, list[_ScoredCode]]
    ) -> dict[str, list[_ScoredCode]]:
        nodes = self._as_nodes(buckets)
        if not nodes:
            return {field: [] for field in buckets}
        try:
            scored_nodes = self._postprocessor.postprocess_nodes(nodes, query_bundle=query)
        except Exception:
            logger.warning("Cross-encoder re-rank failed; keeping every bucket's candidates unranked.")
            return buckets
        return self._grouped_survivors(scored_nodes, buckets)

    def _as_nodes(self, buckets: dict[str, list[_ScoredCode]]) -> list[NodeWithScore]:
        nodes = []
        for bucket, candidates in buckets.items():
            for index, candidate in enumerate(candidates):
                node = TextNode(text=candidate.code, metadata={"bucket": bucket, "candidate_index": index})
                nodes.append(NodeWithScore(node=node, score=None))
        return nodes

    def _grouped_survivors(
        self, scored_nodes: list[NodeWithScore], buckets: dict[str, list[_ScoredCode]]
    ) -> dict[str, list[_ScoredCode]]:
        ranked = sorted(scored_nodes, key=lambda node: node.score if node.score is not None else float("-inf"), reverse=True)
        survivors: dict[str, list[_ScoredCode]] = {field: [] for field in buckets}
        for node in ranked[: self._max_candidates]:
            bucket = node.node.metadata["bucket"]
            index = node.node.metadata["candidate_index"]
            survivors[bucket].append(buckets[bucket][index])
        return survivors
