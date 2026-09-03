"""
    Cross-encoder precision pass over dry_matching.py's over-fetched
    similarity buckets, before DRY's evidence ever reaches an LLM. A
    bi-encoder must commit to one representation per corpus, since both
    sides of the comparison share one vector space — explanation for the
    semantic bucket, raw code for the code and lexical buckets. A
    cross-encoder scores a pair jointly and needs no shared space, so every
    candidate's own code (already carried by every match type) can be
    scored here regardless of which representation retrieved it.

    structural_matches are untouched: an exact structural-hash match is
    already a certain clone, nothing for a relevance score to confirm.
"""
import logging
from typing import Protocol, TypeVar

from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from code_reviewer.rag.dry_matching import ChunkHistoryMatch

logger = logging.getLogger(__name__)

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_CANDIDATE_CAP = 30


class _ScoredCode(Protocol):
    code: str


_ScoredCodeT = TypeVar("_ScoredCodeT", bound=_ScoredCode)


class _NodePostprocessor(Protocol):
    def postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]: ...


class HistoryMatchReranker:
    """Re-scores one chunk's similarity-candidate buckets (semantic,
    raw-code, lexical) by how relevant each candidate's own code actually
    is to the chunk under review."""

    def __init__(self, score_floor: float, postprocessor: _NodePostprocessor | None = None) -> None:
        self._score_floor = score_floor
        self._postprocessor = postprocessor or SentenceTransformerRerank(
            model=CROSS_ENCODER_MODEL, top_n=RERANK_CANDIDATE_CAP
        )

    def rerank(self, query_code: str, match: ChunkHistoryMatch) -> ChunkHistoryMatch:
        query = QueryBundle(query_str=query_code)
        return ChunkHistoryMatch(
            chunk=match.chunk,
            structural_matches=match.structural_matches,
            semantic_matches=self._survivors(query, match.semantic_matches),
            code_matches=self._survivors(query, match.code_matches),
            lexical_matches=self._survivors(query, match.lexical_matches),
        )

    def _survivors(self, query: QueryBundle, candidates: list[_ScoredCodeT]) -> list[_ScoredCodeT]:
        if not candidates:
            return []
        nodes = [self._as_node(index, candidate) for index, candidate in enumerate(candidates)]
        try:
            scored_nodes = self._postprocessor.postprocess_nodes(nodes, query_bundle=query)
        except Exception:
            logger.warning("Cross-encoder re-rank failed; keeping this bucket's candidates unranked.")
            return candidates
        return [
            candidates[node.node.metadata["candidate_index"]]
            for node in scored_nodes
            if node.score is not None and node.score >= self._score_floor
        ]

    def _as_node(self, index: int, candidate: _ScoredCodeT) -> NodeWithScore:
        node = TextNode(text=candidate.code, metadata={"candidate_index": index})
        return NodeWithScore(node=node, score=None)
