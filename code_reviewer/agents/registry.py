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
from code_reviewer.agents.dry import DryAgent
from code_reviewer.agents.errors import ErrorsAgent
from code_reviewer.agents.llm.base import LLMInterface
from code_reviewer.agents.naming import NamingAgent
from code_reviewer.agents.solid_1 import SolidSrpOcpAgent
from code_reviewer.agents.solid_2 import SolidLspDipAgent
from code_reviewer.agents.testability import TestabilityAgent
from code_reviewer.rag.code_similarity_index import CodeSimilarityIndex
from code_reviewer.rag.exemplar_injection import ExemplarCorpora
from code_reviewer.rag.exemplars import ExemplarStore
from code_reviewer.rag.indexer import LlamaIndexRagManager
from code_reviewer.rag.shared_exemplars import SharedExemplarStore
from code_reviewer.rag.structural_hash_store import StructuralHashStore


@dataclass(frozen=True)
class AgentsContainer:
    """The complete set of built review agents, grouped by dispatch category."""

    file_agents: list[FileSizeAwareAgentBase]
    chunk_agents: list[AgentBase]
    tcase_agent: CoverageGapAgent
    dry_agent: DryAgent
    rag_manager: LlamaIndexRagManager
    structural_hash_store: StructuralHashStore
    code_similarity_index: CodeSimilarityIndex
    exemplar_store: ExemplarStore | None = None
    shared_exemplar_store: SharedExemplarStore | None = None


def build_agent_roster(
    llm: LLMInterface | None = None,
    rag_manager: LlamaIndexRagManager | None = None,
    structural_hash_store: StructuralHashStore | None = None,
    code_similarity_index: CodeSimilarityIndex | None = None,
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
    exemplar_store = exemplar_store or ExemplarStore()
    shared_exemplar_store = shared_exemplar_store or SharedExemplarStore()
    corpora = ExemplarCorpora(repo=exemplar_store, shared=shared_exemplar_store)
    file_agents = [
        SolidSrpOcpAgent(llm, corpora),
        SolidLspDipAgent(llm, corpora),
        CohesionAgent(llm, corpora),
        CouplingAgent(llm, rag_manager, corpora),
        ArchitectureAgent(llm, rag_manager),
        BoundariesAgent(llm),
    ]
    chunk_agents = [
        NamingAgent(llm),
        ErrorsAgent(llm),
        CommentsAgent(llm),
        ConcurrencyAgent(llm),
        ComplexityAgent(llm),
        TestabilityAgent(llm),
    ]
    tcase_agent = CoverageGapAgent(llm)
    dry_agent = DryAgent(llm)

    return AgentsContainer(
        file_agents=file_agents,
        chunk_agents=chunk_agents,
        tcase_agent=tcase_agent,
        dry_agent=dry_agent,
        rag_manager=rag_manager,
        structural_hash_store=structural_hash_store,
        code_similarity_index=code_similarity_index,
        exemplar_store=exemplar_store,
        shared_exemplar_store=shared_exemplar_store,
    )
