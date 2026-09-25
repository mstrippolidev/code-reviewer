"""
    Dispatches one prepared file to every built agent, splitting chunk
    agents' work into per-function/class pieces once the file is too
    large for a single call.
"""
import logging
import time
from collections.abc import Awaitable, Callable

from langchain_core.runnables import RunnableLambda, RunnableParallel

from code_reviewer.agents.base import AgentBase, FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.agents.llm.middleware import rating_from_incidents
from code_reviewer.agents.llm.timeout import call_with_hard_timeout
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.code_splitter.interface import CodeChunk, CodeSplitterInterface
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.pipeline.line_offset import offset_incidents
from code_reviewer.rag.dry_evidence import extract_snippet
from code_reviewer.rag.dry_matching import ChunkHistoryMatch, CrossHistoryDuplicateFinder, DuplicateEvidenceSources
from code_reviewer.rag.dry_review import build_dry_review_entry
from code_reviewer.rag.errors import (
    ChunkExplanationError,
    PairingJudgeInvocationError,
    PairingQueryRewriteError,
    VectorStoreQueryError,
)
from code_reviewer.rag.tcase_pairing_retry import CorrectiveTestPairingFinder
from code_reviewer.schemas.paired import Pairing, build_standalone_test_file_content
from code_reviewer.schemas.review import (
    AgentOutput,
    AgentReviewEntry,
    CodeKey,
    Incident,
    Priority,
    ReviewScope,
    SizeStatus,
)
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

logger = logging.getLogger(__name__)

_CHUNKED_SIZE_STATUSES = (SizeStatus.SOFT_LIMIT, SizeStatus.HARD_LIMIT_EXCEEDED)
_TEST_FILE_HYGIENE_KEYS = frozenset({CodeKey.VAR, CodeKey.ERR, CodeKey.CMT})
_PAIRING_LOOKUP_ERRORS = (
    VectorStoreQueryError,
    ChunkExplanationError,
    PairingJudgeInvocationError,
    PairingQueryRewriteError,
)


def review_file(
    prepared_file: PreparedFile,
    agents_container: AgentsContainer,
    splitter: CodeSplitterInterface | None = None,
) -> list[AgentReviewEntry]:
    """Dispatches a prepared file to every built agent.

    Args:
        prepared_file: A file that already passed every pipeline guard,
            paired with its test files and classified by size.
        agents_container: The complete set of built agents, grouped for
            dispatch.
        splitter: Splits chunk agents' work into per-function/class
            pieces once the file is too large for one call. Defaults to
            PythonCodeSplit() — this codebase is Python-only today.

    Returns:
        One AgentReviewEntry per agent that reviewed this file.
    """
    splitter = splitter or PythonCodeSplit()
    standalone = _is_standalone_test_review(prepared_file)
    entries = [] if standalone else _run_file_agents(prepared_file, agents_container.file_agents)
    chunk_agents = _scoped_chunk_agents(agents_container.chunk_agents, standalone)
    chunk_entries = _run_chunk_agents(prepared_file, chunk_agents, splitter)
    _apply_cmplx_soft_limit_incident(chunk_entries, prepared_file)
    entries += chunk_entries
    entries.append(_run_tcase_agent(prepared_file, agents_container))
    if not standalone:
        entries.append(_run_dry(agents_container, prepared_file))
    return entries


def _is_standalone_test_review(prepared_file: PreparedFile) -> bool:
    return prepared_file.review_scope == ReviewScope.TEST_FILE_STANDALONE


def _scoped_chunk_agents(chunk_agents: list[AgentBase], standalone: bool) -> list[AgentBase]:
    if not standalone:
        return chunk_agents
    return [agent for agent in chunk_agents if agent.get_agent_key() in _TEST_FILE_HYGIENE_KEYS]


def _tcase_content(prepared_file: PreparedFile, test_pairing_finder: CorrectiveTestPairingFinder | None) -> str:
    if _is_standalone_test_review(prepared_file):
        return build_standalone_test_file_content(prepared_file.source_file)
    test_files = _tcase_test_files(prepared_file, test_pairing_finder)
    return Pairing(source_file=prepared_file.source_file, test_files=test_files).get_content()


def _run_file_agents(
    prepared_file: PreparedFile, file_agents: list[FileSizeAwareAgentBase]
) -> list[AgentReviewEntry]:
    """Runs every file agent once, on the whole file, every size band."""
    source = prepared_file.source_file
    review_meta = FileReviewMeta(size_status=prepared_file.size_status, repo_data=prepared_file.repo_data)
    return [agent.execute_agent(source.content, source.file_path, review_meta).review[0] for agent in file_agents]


def _run_chunk_agent(
    agent: AgentBase,
    ctx: dict[str, str | SizeStatus],
    splitter: CodeSplitterInterface,
) -> AgentReviewEntry:
    """Runs one chunk agent on a shared context, splitting into per-
    function/class chunks once the file is at or past the soft size limit."""
    size_status = ctx["size_status"]
    if size_status not in _CHUNKED_SIZE_STATUSES:
        return agent.execute_agent(ctx["code"], ctx["file_path"]).review[0]

    code_chunks = splitter.split_code(ctx["code"])
    return _run_chunked_agent(agent, ctx["file_path"], code_chunks)


def _run_chunk_agents(
    prepared_file: PreparedFile,
    chunk_agents: list[AgentBase],
    splitter: CodeSplitterInterface,
) -> list[AgentReviewEntry]:
    """Runs every chunk agent once per file, splitting into per-function/
    class chunks once the file is at or past the soft size limit."""
    source = prepared_file.source_file
    if prepared_file.size_status not in _CHUNKED_SIZE_STATUSES:
        return [agent.execute_agent(source.content, source.file_path).review[0] for agent in chunk_agents]

    code_chunks = splitter.split_code(source.content)
    return [_run_chunked_agent(agent, source.file_path, code_chunks) for agent in chunk_agents]


def _get_chunks(chunks: list[CodeChunk]) -> list[str]:
    """Converts code chunks to their raw text, in source order."""
    return [chunk.code for chunk in chunks]


def _run_chunked_agent(agent: AgentBase, file_path: str, chunks: list[CodeChunk]) -> AgentReviewEntry:
    """Runs one chunk agent across every chunk, merging the results into
    a single file-level entry with file-absolute incident positions."""
    incidents: list[Incident] = []
    chunk_str = _get_chunks(chunks)
    results = agent.execute_agent_batch(chunk_str, file_path)
    for i in range(len(chunks)):
        incidents += offset_incidents(results[i].review[0].incidents, chunks[i].start_line)
    return AgentReviewEntry(
        file_path=file_path,
        code_key=agent.get_agent_key(),
        incidents=incidents,
        rating=rating_from_incidents(incidents),
    )


def _run_tcase_agent(prepared_file: PreparedFile, agents_container: AgentsContainer) -> AgentReviewEntry:
    """Runs TCASE once, whole-file, via its paired test-file content —
    never chunked, regardless of size band."""
    content = _tcase_content(prepared_file, agents_container.test_pairing_finder)
    return agents_container.tcase_agent.execute_agent(content, prepared_file.source_file.file_path).review[0]


def _tcase_test_files(
    prepared_file: PreparedFile, test_pairing_finder: CorrectiveTestPairingFinder | None
) -> list[SubmittedFile]:
    """Falls back to the repo's indexed corpus only when no test file rode along in the submission.

    A failed corpus lookup degrades to no test files, never to a failed TCASE review.
    """
    if prepared_file.test_files or prepared_file.repo_data is None or test_pairing_finder is None:
        return prepared_file.test_files
    try:
        return test_pairing_finder.find_test_files(prepared_file.repo_data, prepared_file.source_file)
    except _PAIRING_LOOKUP_ERRORS:
        logger.warning(
            "corpus test-file pairing failed file_path=%s; reviewing without test files",
            prepared_file.source_file.file_path,
            exc_info=True,
        )
        return []


def _run_dry(agents_container: AgentsContainer, prepared_file: PreparedFile) -> AgentReviewEntry:
    """Exact structural-hash matches need no LLM judgment — the hash
    already proves the duplicate — so only the fuzzy, re-ranked candidates
    reach the DRY judge; a file with no evidence of either kind short-
    circuits to a clean result with no LLM call at all."""
    file_path = prepared_file.source_file.file_path
    intra_pr_groups = prepared_file.intra_pr_duplicates
    history_matches = _gather_dry_history_matches(agents_container, prepared_file)
    if not intra_pr_groups and not history_matches:
        return AgentReviewEntry(file_path=file_path, code_key=CodeKey.DRY, incidents=[])
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


def _gather_dry_history_matches(agents_container: AgentsContainer, prepared_file: PreparedFile) -> list[ChunkHistoryMatch]:
    """Looks up what this file duplicates in the repo's indexed history —
    skipped entirely for a standalone review with no repo context, Every match's
    similarity buckets are then re-ranked by relevance to the chunk's own
    code, so DRY's evidence carries the over-fetched buckets' survivors,
    not their raw recall."""
    if prepared_file.repo_data is None:
        return []
    evidence_sources = DuplicateEvidenceSources(
        structural_hash_store=agents_container.structural_hash_store,
        embedding_index=agents_container.rag_manager,
        code_similarity_index=agents_container.code_similarity_index,
    )
    finder = CrossHistoryDuplicateFinder(evidence_sources, prepared_file.repo_data)
    content = prepared_file.source_file.content
    matches = finder.find(prepared_file.source_file.file_path, content)
    reranker = agents_container.history_match_reranker
    reranked = [reranker.rerank(extract_snippet(content, match.chunk), match) for match in matches]
    return [match for match in reranked if _has_evidence(match)]


def _has_evidence(match: ChunkHistoryMatch) -> bool:
    """A chunk whose every bucket the re-ranker emptied out carries nothing
    for DRY to say, the same standard CrossHistoryDuplicateFinder itself
    already applies before re-ranking ever runs."""
    return bool(match.structural_matches or match.semantic_matches or match.code_matches or match.lexical_matches)


def _apply_cmplx_soft_limit_incident(entries: list[AgentReviewEntry], prepared_file: PreparedFile) -> None:
    """Appends CMPLX's file-size incident when the file is in the soft
    limit band — a line-count threshold, not a judgment call, so it's
    computed deterministically rather than asked of the LLM. No chunk
    call can report this itself: each one only ever sees its own
    function/class in isolation, never the whole file's line count."""
    if prepared_file.size_status != SizeStatus.SOFT_LIMIT:
        return
    cmplx_entry = next((entry for entry in entries if entry.code_key == CodeKey.CMPLX), None)
    if cmplx_entry is None:
        return
    cmplx_entry.incidents.append(_soft_limit_incident(prepared_file.source_file.content))
    cmplx_entry.rating = rating_from_incidents(cmplx_entry.incidents)


def _soft_limit_incident(content: str) -> Incident:
    line_count = content.count("\n")
    return Incident(
        priority=Priority.MEDIUM,
        line_position=f"1-{line_count}",
        description=(
            f"File has {line_count} lines, in the 500-750 soft limit band. "
            "Larger files raise cognitive load regardless of any single "
            "function's own complexity."
        ),
        advice="Split this file into smaller modules under 500 lines each, grouped by responsibility.",
    )


async def review_file_runnable(
    prepared_file: PreparedFile,
    agents_container: AgentsContainer,
    splitter: CodeSplitterInterface | None = None,
    on_agent_reviewed: Callable[[CodeKey, AgentReviewEntry], Awaitable[None]] | None = None,
) -> list[AgentReviewEntry]:
    """Dispatches a prepared file to every built agent, fanned out
    concurrently via a single RunnableParallel instead of sequential calls.

    Args:
        prepared_file: A file that already passed every pipeline guard,
            paired with its test files and classified by size.
        agents_container: The complete set of built agents, grouped for
            dispatch.
        splitter: Splits chunk agents' work into per-function/class
            pieces once the file is too large for one call. Defaults to
            PythonCodeSplit() — this codebase is Python-only today.
        on_agent_reviewed: Optional progress hook, awaited with one agent's
            code_key and its finished AgentReviewEntry the instant that
            branch resolves — other branches may still be running.

    Returns:
        One AgentReviewEntry per agent that reviewed this file.
    """
    splitter = splitter or PythonCodeSplit()
    standalone = _is_standalone_test_review(prepared_file)
    file_agents = [] if standalone else agents_container.file_agents
    chunk_agents = _scoped_chunk_agents(agents_container.chunk_agents, standalone)
    context = {
        "code": prepared_file.source_file.content,
        "file_path": prepared_file.source_file.file_path,
        "size_status": prepared_file.size_status,
        "repo_data": prepared_file.repo_data,
    }
    raw_branches = (
        {agent.get_agent_key().value: _file_agent_branch(agent) for agent in file_agents}
        | {agent.get_agent_key().value: _chunk_agent_branch(agent, splitter) for agent in chunk_agents}
        | {"TCASE": _tcase_branch(agents_container, prepared_file)}
    )
    if not standalone:
        raw_branches["DRY"] = _dry_branch(agents_container, prepared_file)
    branches = {key: branch.with_config({"run_name": key}) for key, branch in raw_branches.items()}
    config = {"max_concurrency": get_settings().max_dispatch_concurrency}
    results: dict[str, AgentOutput | AgentReviewEntry] = {}
    started_at: dict[str, float] = {}
    file_path = prepared_file.source_file.file_path
    logger.info("dispatch started file_path=%s agent_count=%d", file_path, len(branches))
    async for event in RunnableParallel(branches).astream_events(context, version="v2", config=config):
        code_key = event["name"]
        if code_key not in branches:
            continue
        if event["event"] == "on_chain_start":
            started_at[code_key] = time.monotonic()
            logger.info("agent started code_key=%s file_path=%s", code_key, file_path)
            continue
        if event["event"] != "on_chain_end":
            continue
        elapsed_seconds = time.monotonic() - started_at.get(code_key, time.monotonic())
        result = event["data"]["output"]
        results[code_key] = result
        logger.info(
            "agent finished code_key=%s file_path=%s elapsed_seconds=%.2f", code_key, file_path, elapsed_seconds
        )
        if on_agent_reviewed is not None:
            await _report_agent_reviewed(CodeKey(code_key), result, on_agent_reviewed)

    logger.info("dispatch finished file_path=%s agents_completed=%d", file_path, len(results))
    entries = _unpack_runnable_results(results)
    _apply_cmplx_soft_limit_incident(entries, prepared_file)
    return entries


async def _report_agent_reviewed(
    code_key: CodeKey,
    result: AgentOutput | AgentReviewEntry,
    on_agent_reviewed: Callable[[CodeKey, AgentReviewEntry], Awaitable[None]],
) -> None:
    """Unwraps one branch's raw result the same way _unpack_runnable_results
    does, then reports it the instant this one agent finishes rather than
    waiting for every other branch to also resolve."""
    entry = result.review[0] if isinstance(result, AgentOutput) else result
    await on_agent_reviewed(code_key, entry)


_AGENT_FAILURE_CLIENT_MESSAGE = "This agent failed to complete its review due to an internal error."


def _isolate_agent_failure(
    code_key: CodeKey, file_path: str | None, produce: Callable[[], AgentOutput | AgentReviewEntry]
) -> AgentOutput | AgentReviewEntry:
    """Runs one branch's own call, converting a raised exception into a
    failed AgentReviewEntry instead of letting it escape RunnableParallel —
    one agent's provider outage or tool-recursion timeout must never destroy
    every other agent's already-finished result for this same file. The raw
    exception is logged server-side only; the client-facing entry carries a
    fixed, generic message so internal error detail is never exposed to it."""
    try:
        return produce()
    except Exception as error:
        logger.error(
            "agent dispatch failed code_key=%s file_path=%s error=%s", code_key, file_path, error, exc_info=True
        )
        return _agent_failure_entry(code_key, file_path)


def _agent_failure_entry(code_key: CodeKey, file_path: str | None) -> AgentReviewEntry:
    return AgentReviewEntry(
        file_path=file_path,
        code_key=code_key,
        rating=0,
        incidents=[],
        failed=True,
        failure_reason=_AGENT_FAILURE_CLIENT_MESSAGE,
    )


def _file_agent_branch(agent: FileSizeAwareAgentBase) -> RunnableLambda:
    """Builds a branch that runs one file agent against the shared context,
    isolated so its own failure can't take down the other branches."""
    code_key = agent.get_agent_key()
    return RunnableLambda(
        lambda ctx: _isolate_agent_failure(
            code_key,
            ctx["file_path"],
            lambda: agent.execute_agent(
                ctx["code"],
                ctx["file_path"],
                FileReviewMeta(size_status=ctx["size_status"], repo_data=ctx.get("repo_data")),
            ),
        )
    )


def _chunk_agent_branch(agent: AgentBase, splitter: CodeSplitterInterface) -> RunnableLambda:
    """Builds a branch that runs one chunk agent against the shared context,
    isolated so its own failure can't take down the other branches."""
    code_key = agent.get_agent_key()
    return RunnableLambda(
        lambda ctx: _isolate_agent_failure(code_key, ctx["file_path"], lambda: _run_chunk_agent(agent, ctx, splitter))
    )


def _tcase_branch(agents_container: AgentsContainer, prepared_file: PreparedFile) -> RunnableLambda:
    """Builds a branch that runs TCASE against its own paired content,
    isolated so its own failure can't take down the other branches."""
    return RunnableLambda(
        lambda ctx: _isolate_agent_failure(
            CodeKey.TCASE, ctx["file_path"], lambda: _run_tcase_agent(prepared_file, agents_container)
        )
    )


def _dry_branch(agents_container: AgentsContainer, prepared_file: PreparedFile) -> RunnableLambda:
    """Builds a branch that runs DRY against its own assembled evidence,
    isolated so its own failure can't take down the other branches."""
    file_path = prepared_file.source_file.file_path
    return RunnableLambda(
        lambda ctx: _isolate_agent_failure(CodeKey.DRY, file_path, lambda: _run_dry(agents_container, prepared_file))
    )


def _unpack_runnable_results(results: dict[str, AgentOutput | AgentReviewEntry]) -> list[AgentReviewEntry]:
    """Extracts one AgentReviewEntry per branch from a RunnableParallel
    result. File agent and TCASE branches return a raw AgentOutput
    (unwrapped here); chunk agent branches already return an unwrapped
    AgentReviewEntry, since chunked ones are merged from multiple calls."""
    entries = []
    for result in results.values():
        if isinstance(result, AgentOutput):
            entries.append(result.review[0])
        else:
            entries.append(result)
    return entries
