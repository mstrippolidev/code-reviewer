"""
    Cross-encoder ranking over both TCASE pairing buckets at once, so the
    pairing judge only ever sees the few candidates most worth asking about.
    Selection is by rank, never an absolute score: this model's raw score is
    only comparable between candidates scored against the same query.
"""
import logging
from typing import Protocol

from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from code_reviewer.rag.rerank import CROSS_ENCODER_MODEL, RERANK_CANDIDATE_CAP
from code_reviewer.rag.tcase_pairing import PairingBuckets, PairingCandidate

logger = logging.getLogger(__name__)

PAIRING_RERANK_MAX_CANDIDATES = 5


class _NodePostprocessor(Protocol):
    def postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]: ...


class PairingReranker:
    """Ranks deterministic and semantic pairing candidates jointly, keeping the top max_candidates."""

    def __init__(self, max_candidates: int, postprocessor: _NodePostprocessor | None = None) -> None:
        self._max_candidates = max_candidates
        self._postprocessor = postprocessor or SentenceTransformerRerank(
            model=CROSS_ENCODER_MODEL, top_n=RERANK_CANDIDATE_CAP
        )

    def rerank(self, query: str, buckets: PairingBuckets) -> list[PairingCandidate]:
        """A scoring failure degrades to the candidates in bucket order, deterministic first, still capped."""
        candidates = _unique_candidates(buckets)
        if not candidates:
            return []
        try:
            scored_nodes = self._postprocessor.postprocess_nodes(
                _as_nodes(candidates), query_bundle=QueryBundle(query_str=query)
            )
        except Exception:
            logger.warning("Cross-encoder re-rank of pairing candidates failed; keeping them unranked.")
            return candidates[: self._max_candidates]
        ranked = sorted(scored_nodes, key=_score_or_lowest, reverse=True)
        return [candidates[node.node.metadata["candidate_index"]] for node in ranked[: self._max_candidates]]


def _unique_candidates(buckets: PairingBuckets) -> list[PairingCandidate]:
    unique_by_path: dict[str, PairingCandidate] = {}
    for candidate in [*buckets.deterministic, *buckets.semantic]:
        unique_by_path.setdefault(candidate.file_path, candidate)
    return list(unique_by_path.values())


def _as_nodes(candidates: list[PairingCandidate]) -> list[NodeWithScore]:
    return [
        NodeWithScore(node=TextNode(text=candidate.content, metadata={"candidate_index": index}), score=None)
        for index, candidate in enumerate(candidates)
    ]


def _score_or_lowest(node: NodeWithScore) -> float:
    return node.score if node.score is not None else float("-inf")
