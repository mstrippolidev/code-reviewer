"""
    DRY's per-file workflow, shared by the review pipeline and by callers that
    only want to know whether a piece of code already exists in a repo's history.
"""
from opentelemetry import trace

from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.guardrails.intake_screen import run_intake_screen
from code_reviewer.pipeline.file_size import run_file_size_guard
from code_reviewer.pipeline.raw_character_guard import run_raw_character_guard
from code_reviewer.rag.dry_evidence import extract_snippet
from code_reviewer.rag.dry_matching import ChunkHistoryMatch, CrossHistoryDuplicateFinder, DuplicateEvidenceSources
from code_reviewer.rag.dry_review import build_dry_review_entry
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.schemas.review import AgentReviewEntry, CodeKey, SizeStatus
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile
from code_reviewer.telemetry.metrics import pipeline_metrics
from code_reviewer.telemetry.rag_metrics import RetrievalSource, rag_metrics

tracer = trace.get_tracer(__name__)

SNIPPET_FILE_PATH = "<submitted snippet>"
DRY_REQUIRES_REPO_REASON = (
    "Duplication checks compare against a registered repository's indexed history, "
    "so DRY is only available for GitHub-connected reviews."
)


def check_snippet_for_duplicates(
    agents_container: AgentsContainer, repo_data: RepoData, content: str
) -> AgentReviewEntry:
    """Runs DRY on a snippet that is not part of the repo, against the repo's indexed history.

    Raises:
        SubmissionTooLargeError: If the snippet exceeds the raw character cap.
        FileTooLargeError: If the snippet exceeds the line cap.
        IntakeRejectedError: If the snippet is not source code or carries a prompt-injection attempt.
        DryMatchingChunkingError: If the snippet cannot be split into functions and classes.
    """
    run_raw_character_guard(content)
    run_file_size_guard(content)
    run_intake_screen(content, llm=agents_container.intake_llm)
    prepared_file = PreparedFile(
        source_file=SubmittedFile(file_path=SNIPPET_FILE_PATH, content=content),
        size_status=SizeStatus.NORMAL,
        repo_data=repo_data,
    )
    return run_dry(agents_container, prepared_file)


@tracer.start_as_current_span("execute_agent", attributes={"code_reviewer.code_key": CodeKey.DRY.value})
def run_dry(agents_container: AgentsContainer, prepared_file: PreparedFile) -> AgentReviewEntry:
    """Runs DRY on one file and times the run; a file with no repo is skipped, not run."""
    if prepared_file.repo_data is None:
        pipeline_metrics.record_agent_skip(CodeKey.DRY.value, "repo_required")
        return AgentReviewEntry(
            file_path=prepared_file.source_file.file_path,
            code_key=CodeKey.DRY,
            incidents=[],
            skipped=True,
            skip_reason=DRY_REQUIRES_REPO_REASON,
        )
    with pipeline_metrics.track_agent_run(CodeKey.DRY.value):
        return _review_against_history(agents_container, prepared_file, prepared_file.repo_data)


def _review_against_history(
    agents_container: AgentsContainer, prepared_file: PreparedFile, repo_data: RepoData
) -> AgentReviewEntry:
    """Exact structural-hash matches need no LLM judgment, so only the fuzzy,
    re-ranked candidates reach the DRY judge; a file with no evidence of either
    kind returns a clean entry without an LLM call."""
    file_path = prepared_file.source_file.file_path
    intra_pr_groups = prepared_file.intra_pr_duplicates
    history_matches = _gather_history_matches(agents_container, prepared_file.source_file, repo_data)
    if not intra_pr_groups and not history_matches:
        return AgentReviewEntry(file_path=file_path, code_key=CodeKey.DRY, incidents=[])
    with tracer.start_as_current_span("judge_duplicate_candidates"):
        return call_with_hard_timeout(
            lambda: build_dry_review_entry(
                file_path,
                prepared_file.source_file.content,
                intra_pr_groups,
                history_matches,
                agents_container.dry_judge,
            ),
            timeout=get_settings().dry_agent_timeout_seconds,
        )


@tracer.start_as_current_span("find_duplicate_candidates")
def _gather_history_matches(
    agents_container: AgentsContainer, source_file: SubmittedFile, repo_data: RepoData
) -> list[ChunkHistoryMatch]:
    evidence_sources = DuplicateEvidenceSources(
        structural_hash_store=agents_container.structural_hash_store,
        embedding_index=agents_container.rag_manager,
        code_similarity_index=agents_container.code_similarity_index,
    )
    finder = CrossHistoryDuplicateFinder(evidence_sources, repo_data)
    matches = finder.find(source_file.file_path, source_file.content)
    reranker = agents_container.history_match_reranker
    reranked = [reranker.rerank(extract_snippet(source_file.content, match.chunk), match) for match in matches]
    kept = [match for match in reranked if _has_evidence(match)]
    for match in kept:
        _record_candidates(match)
    return kept


def _record_candidates(match: ChunkHistoryMatch) -> None:
    """Counts the candidates of each kind that survived re-ranking for one chunk."""
    rag_metrics.record_dry_candidates(RetrievalSource.STRUCTURAL, len(match.structural_matches))
    rag_metrics.record_dry_candidates(RetrievalSource.SEMANTIC, len(match.semantic_matches))
    rag_metrics.record_dry_candidates(RetrievalSource.CODE, len(match.code_matches))
    rag_metrics.record_dry_candidates(RetrievalSource.LEXICAL, len(match.lexical_matches))


def _has_evidence(match: ChunkHistoryMatch) -> bool:
    return bool(match.structural_matches or match.semantic_matches or match.code_matches or match.lexical_matches)
