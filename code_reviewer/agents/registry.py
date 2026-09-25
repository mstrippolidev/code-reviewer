"""
    File that will registry and start all the agents.
"""
from dataclasses import dataclass

from code_reviewer.agents.architecture import ArchitectureAgent
from code_reviewer.agents.base import AgentBase, FileSizeAwareAgentBase
from code_reviewer.agents.boundaries import BoundariesAgent
from code_reviewer.agents.cohesion import CohesionAgent
from code_reviewer.agents.comments import CommentsAgent
from code_reviewer.agents.complexity import ComplexityAgent
from code_reviewer.agents.concurrency import ConcurrencyAgent
from code_reviewer.agents.coupling import CouplingAgent
from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.errors import ErrorsAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.naming import NamingAgent
from code_reviewer.agents.solid_1 import SolidSrpOcpAgent
from code_reviewer.agents.solid_2 import SolidLspDipAgent
from code_reviewer.agents.testability import TestabilityAgent
from code_reviewer.config.settings import get_settings
from code_reviewer.rag.code_similarity_index import CodeSimilarityIndex
from code_reviewer.rag.dry_judge import DryJudge, DryJudgeLike
from code_reviewer.rag.dry_judge_split import SizeGuardedDryJudge, SplitConfig
from code_reviewer.rag.exemplar_injection import ExemplarCorpora
from code_reviewer.rag.exemplars import ExemplarStore
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.rerank import HistoryMatchReranker
from code_reviewer.rag.shared_exemplars import SharedExemplarStore
from code_reviewer.rag.structural_hash_store import StructuralHashStore
from code_reviewer.rag.tcase_pairing import PairingCandidateFinder, PairingEvidenceSources
from code_reviewer.rag.tcase_pairing_judge import PairingJudge
from code_reviewer.rag.tcase_pairing_query_rewrite import PairingQueryRewriter
from code_reviewer.rag.tcase_pairing_rerank import PAIRING_RERANK_MAX_CANDIDATES, PairingReranker
from code_reviewer.rag.tcase_pairing_retry import CorrectiveTestPairingFinder, PairingCorrectionTools
from code_reviewer.schemas.review import CodeKey


@dataclass(frozen=True)
class AgentsContainer:
    """The complete set of built review agents, grouped by dispatch category."""

    file_agents: list[FileSizeAwareAgentBase]
    chunk_agents: list[AgentBase]
    tcase_agent: CoverageGapAgent
    dry_judge: DryJudgeLike
    rag_manager: LlamaIndexRagManager
    structural_hash_store: StructuralHashStore
    code_similarity_index: CodeSimilarityIndex
    history_match_reranker: HistoryMatchReranker
    exemplar_store: ExemplarStore | None = None
    shared_exemplar_store: SharedExemplarStore | None = None
    test_pairing_finder: CorrectiveTestPairingFinder | None = None


def build_agent_roster(
    llm: LLMInterface | None = None,
    rag_manager: LlamaIndexRagManager | None = None,
    structural_hash_store: StructuralHashStore | None = None,
    code_similarity_index: CodeSimilarityIndex | None = None,
    history_match_reranker: HistoryMatchReranker | None = None,
    exemplar_store: ExemplarStore | None = None,
    shared_exemplar_store: SharedExemplarStore | None = None,
) -> AgentsContainer:
    """Builds one instance of every agent, grouped for dispatch.

    Args:
        llm: Provider every agent is built against. Defaults to each
            agent's own default (a local OllamaLLM()) when not given.
        rag_manager: Shared RAG dependency ARCH/COUP use for their
            cross-file evidence hop, and DRY uses for its cross-history
            semantic pass. Defaults to a real LlamaIndexRagManager() when
            not given — same pattern as llm's own default.
        structural_hash_store: Shared RAG dependency DRY uses for its
            cross-history exact-match pass. Defaults to a real
            StructuralHashStore() when not given, same pattern as
            rag_manager's own default.
        code_similarity_index: Shared RAG dependency DRY uses for its
            cross-history raw-code and BM25 passes. Defaults to a real
            CodeSimilarityIndex() when not given, same pattern as
            rag_manager's own default.
        history_match_reranker: Cross-encoder relevance-ranking pass over
            DRY's cross-history candidates, keeping only the top-ranked few
            before the DRY judge sees them. Defaults to a real
            HistoryMatchReranker() when not given, same pattern as
            rag_manager's own default.
        exemplar_store: Per-repo corpus of known-good code the 2.0-weight
            agents draw few-shot context from. Defaults to a real ExemplarStore() when
            not given, same pattern as rag_manager's own default.

    Returns:
        An AgentsContainer holding all 14 built agents. Meant to be built
        once and reused for the app's lifetime, never rebuilt per request.
    """
    rag_manager = rag_manager or LlamaIndexRagManager()
    structural_hash_store = structural_hash_store or StructuralHashStore()
    code_similarity_index = code_similarity_index or CodeSimilarityIndex()
    history_match_reranker = history_match_reranker or HistoryMatchReranker(
        max_candidates=get_settings().dry_rerank_max_candidates
    )
    exemplar_store = exemplar_store or ExemplarStore()
    shared_exemplar_store = shared_exemplar_store or SharedExemplarStore()
    corpora = ExemplarCorpora(repo=exemplar_store, shared=shared_exemplar_store)
    file_agents = [
        SolidSrpOcpAgent(_llm_for(CodeKey.SOLID1, llm), corpora),
        SolidLspDipAgent(_llm_for(CodeKey.SOLID2, llm), corpora),
        CohesionAgent(_llm_for(CodeKey.COH, llm), corpora),
        CouplingAgent(_llm_for(CodeKey.COUP, llm), rag_manager, corpora),
        ArchitectureAgent(_llm_for(CodeKey.ARCH, llm), rag_manager),
        BoundariesAgent(_llm_for(CodeKey.BOUND, llm)),
    ]
    chunk_agents = [
        NamingAgent(_llm_for(CodeKey.VAR, llm)),
        ErrorsAgent(_llm_for(CodeKey.ERR, llm)),
        CommentsAgent(_llm_for(CodeKey.CMT, llm)),
        ConcurrencyAgent(_llm_for(CodeKey.CONC, llm)),
        ComplexityAgent(_llm_for(CodeKey.CMPLX, llm)),
        TestabilityAgent(_llm_for(CodeKey.TEST, llm)),
    ]
    tcase_agent = CoverageGapAgent(_llm_for(CodeKey.TCASE, llm))
    dry_judge: DryJudgeLike = SizeGuardedDryJudge(
        DryJudge(_llm_for(CodeKey.DRY, llm)),
        SplitConfig(
            max_pair_chars=get_settings().dry_judge_max_pair_chars,
            overlap_chars=get_settings().dry_judge_split_overlap_chars,
        ),
    )

    return AgentsContainer(
        file_agents=file_agents,
        chunk_agents=chunk_agents,
        tcase_agent=tcase_agent,
        dry_judge=dry_judge,
        rag_manager=rag_manager,
        structural_hash_store=structural_hash_store,
        code_similarity_index=code_similarity_index,
        history_match_reranker=history_match_reranker,
        exemplar_store=exemplar_store,
        shared_exemplar_store=shared_exemplar_store,
        test_pairing_finder=_build_test_pairing_finder(llm, PairingEvidenceSources(rag_manager, code_similarity_index)),
    )


def _llm_for(code_key: CodeKey, llm: LLMInterface | None) -> LLMInterface | None:
    return llm.for_code_key(code_key) if llm is not None else None


def _fast_llm(llm: LLMInterface | None) -> LLMInterface | None:
    return llm.for_fast_tier() if llm is not None else None


def _build_test_pairing_finder(
    llm: LLMInterface | None, evidence_sources: PairingEvidenceSources
) -> CorrectiveTestPairingFinder:
    fast_llm = _fast_llm(llm)
    return CorrectiveTestPairingFinder(
        finder=PairingCandidateFinder(evidence_sources),
        reranker=PairingReranker(max_candidates=PAIRING_RERANK_MAX_CANDIDATES),
        correction=PairingCorrectionTools(judge=PairingJudge(fast_llm), query_rewriter=PairingQueryRewriter(fast_llm)),
    )
