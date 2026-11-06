"""
    Dispatches one prepared file to every built agent, splitting chunk
    agents' work into per-function/class pieces.
"""
import logging
import time
from collections.abc import Awaitable, Callable

from langchain_core.runnables import RunnableLambda, RunnableParallel
from opentelemetry import trace

from code_reviewer.agents.base import AgentBase, FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.agents.llm.middleware import rating_from_incidents
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.code_splitter.interface import CodeChunk, CodeSplitterInterface
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.pipeline.dry_check import run_dry
from code_reviewer.pipeline.line_offset import offset_incidents
from code_reviewer.prompts.agents.line_numbering import number_lines
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
from code_reviewer.telemetry.metrics import pipeline_metrics
from code_reviewer.telemetry.run_usage import track_usage

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_TEST_FILE_HYGIENE_KEYS = frozenset({CodeKey.VAR, CodeKey.ERR, CodeKey.CMT})
STANDALONE_TEST_FILE_SKIP_REASON = "standalone_test_file"
_TCASE_HEADER_LINE_COUNT = 1
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
            pieces. Defaults to PythonCodeSplit() — this codebase is
            Python-only today.

    Returns:
        One AgentReviewEntry per agent that reviewed this file.
    """
    splitter = splitter or PythonCodeSplit()
    standalone = _is_standalone_test_review(prepared_file)
    _record_standalone_skips(prepared_file, agents_container)
    file_agents = _file_agents_for(prepared_file, agents_container)
    entries = [] if standalone else _run_file_agents(prepared_file, file_agents)
    chunk_agents = _scoped_chunk_agents(agents_container, standalone)
    entries += _run_chunk_agents(prepared_file, chunk_agents, splitter)
    _apply_cmplx_soft_limit_incident(entries, prepared_file)
    if agents_container.is_selected(CodeKey.TCASE):
        entries.append(_run_tcase_agent(prepared_file, agents_container))
    if not standalone and agents_container.is_selected(CodeKey.DRY):
        entries.append(run_dry(agents_container, prepared_file))
    return entries


def _is_standalone_test_review(prepared_file: PreparedFile) -> bool:
    return prepared_file.review_scope == ReviewScope.TEST_FILE_STANDALONE


def _record_standalone_skips(prepared_file: PreparedFile, agents_container: AgentsContainer) -> None:
    """Counts every selected agent that a standalone test file's scope leaves out."""
    if not _is_standalone_test_review(prepared_file):
        return
    left_out = [
        *_file_agents_for(prepared_file, agents_container),
        *(
            agent
            for agent in _scoped_chunk_agents(agents_container, standalone=False)
            if agent.get_agent_key() not in _TEST_FILE_HYGIENE_KEYS
        ),
    ]
    code_keys = [agent.get_agent_key() for agent in left_out]
    if agents_container.is_selected(CodeKey.DRY):
        code_keys.append(CodeKey.DRY)
    for code_key in code_keys:
        pipeline_metrics.record_agent_skip(code_key.value, STANDALONE_TEST_FILE_SKIP_REASON)


def _file_agents_for(
    prepared_file: PreparedFile, agents_container: AgentsContainer
) -> list[FileSizeAwareAgentBase]:
    """COUP and ARCH each have a repo-aware build (cross-file evidence
    tool) and a repo-less one (no tool), selected per file by whether this
    review has repo context."""
    repo_aware = prepared_file.repo_data is not None
    coupling = agents_container.coupling_agent if repo_aware else agents_container.coupling_agent_repoless
    architecture = agents_container.architecture_agent if repo_aware else agents_container.architecture_agent_repoless
    variants = [agent for agent in (coupling, architecture) if agent is not None]
    return [
        agent
        for agent in (*agents_container.file_agents, *variants)
        if agents_container.is_selected(agent.get_agent_key())
    ]


def _scoped_chunk_agents(agents_container: AgentsContainer, standalone: bool) -> list[AgentBase]:
    selected = [
        agent for agent in agents_container.chunk_agents if agents_container.is_selected(agent.get_agent_key())
    ]
    if not standalone:
        return selected
    return [agent for agent in selected if agent.get_agent_key() in _TEST_FILE_HYGIENE_KEYS]


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
    review_meta = FileReviewMeta(
        size_status=prepared_file.size_status,
        repo_data=prepared_file.repo_data,
        call_depth_reports=prepared_file.call_depth_reports,
    )
    return [agent.execute_agent(source.content, source.file_path, review_meta).review[0] for agent in file_agents]


def _run_chunk_agent(
    agent: AgentBase,
    ctx: dict[str, str | SizeStatus],
    splitter: CodeSplitterInterface,
) -> AgentReviewEntry:
    code_chunks = _chunks_or_whole_file(splitter, ctx["code"])
    return _run_chunked_agent(agent, ctx["file_path"], code_chunks)


def _run_chunk_agents(
    prepared_file: PreparedFile,
    chunk_agents: list[AgentBase],
    splitter: CodeSplitterInterface,
) -> list[AgentReviewEntry]:
    code_chunks = _chunks_or_whole_file(splitter, prepared_file.source_file.content)
    return [_run_chunked_agent(agent, prepared_file.source_file.file_path, code_chunks) for agent in chunk_agents]


def _chunks_or_whole_file(splitter: CodeSplitterInterface, content: str) -> list[CodeChunk]:
    """Falls back to one chunk covering the whole file when it has no top-level function or class."""
    code_chunks = splitter.split_code(content)
    if code_chunks:
        return code_chunks
    return [CodeChunk(
        chunk_type="Module", name="<module>", code=content, start_line=1, end_line=content.count("\n") + 1
    )]


def _get_chunks(chunks: list[CodeChunk]) -> list[str]:
    """Converts code chunks to their text, in source order, each line
    prefixed with its chunk-relative line number so a chunk agent reads
    line_position off the prefix instead of counting from the top of the
    chunk — offset_incidents still expects that same 1-indexed
    chunk-relative numbering back."""
    return [number_lines(chunk.code) for chunk in chunks]


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
    never chunked, regardless of size band. Both _tcase_content branches
    (SOURCE FILE:/TEST FILE UNDER REVIEW:) prepend exactly one header line
    before the reviewed file's own content, so TCASE's line numbers are
    always one line ahead of the real file and need the same offsetting
    every chunk agent already gets."""
    content = _tcase_content(prepared_file, agents_container.test_pairing_finder)
    entry = agents_container.tcase_agent.execute_agent(content, prepared_file.source_file.file_path).review[0]
    entry.incidents = offset_incidents(entry.incidents, start_line=1 - _TCASE_HEADER_LINE_COUNT)
    return entry


@tracer.start_as_current_span("find_test_files_for_source_file")
def _tcase_test_files(
    prepared_file: PreparedFile, test_pairing_finder: CorrectiveTestPairingFinder | None
) -> list[SubmittedFile]:
    """Falls back to the repo's indexed corpus only when no test file rode along in the submission.

    A failed corpus lookup degrades to no test files, never to a failed TCASE review.
    """
    if prepared_file.test_files or prepared_file.repo_data is None or test_pairing_finder is None:
        return prepared_file.test_files
    with track_usage(f"pairing file={prepared_file.source_file.file_path}"):
        try:
            return test_pairing_finder.find_test_files(prepared_file.repo_data, prepared_file.source_file)
        except _PAIRING_LOOKUP_ERRORS:
            logger.warning(
                "corpus test-file pairing failed file_path=%s; reviewing without test files",
                prepared_file.source_file.file_path,
                exc_info=True,
            )
            return []


def _apply_cmplx_soft_limit_incident(entries: list[AgentReviewEntry], prepared_file: PreparedFile) -> None:
    """Appends CMPLX's file-size incident when the file is in the soft
    limit band — a line-count threshold, not a judgment call, so it's
    computed deterministically rather than asked of the LLM."""
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
            pieces. Defaults to PythonCodeSplit() — this codebase is
            Python-only today.
        on_agent_reviewed: Optional progress hook, awaited with one agent's
            code_key and its finished AgentReviewEntry the instant that
            branch resolves — other branches may still be running.

    Returns:
        One AgentReviewEntry per agent that reviewed this file.
    """
    splitter = splitter or PythonCodeSplit()
    standalone = _is_standalone_test_review(prepared_file)
    _record_standalone_skips(prepared_file, agents_container)
    file_agents = [] if standalone else _file_agents_for(prepared_file, agents_container)
    chunk_agents = _scoped_chunk_agents(agents_container, standalone)
    context = {
        "code": prepared_file.source_file.content,
        "file_path": prepared_file.source_file.file_path,
        "size_status": prepared_file.size_status,
        "repo_data": prepared_file.repo_data,
        "call_depth_reports": prepared_file.call_depth_reports,
    }
    raw_branches = (
        {agent.get_agent_key().value: _file_agent_branch(agent) for agent in file_agents}
        | {agent.get_agent_key().value: _chunk_agent_branch(agent, splitter) for agent in chunk_agents}
    )
    if agents_container.is_selected(CodeKey.TCASE):
        raw_branches["TCASE"] = _tcase_branch(agents_container, prepared_file)
    if not standalone and agents_container.is_selected(CodeKey.DRY):
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
                FileReviewMeta(
                    size_status=ctx["size_status"],
                    repo_data=ctx.get("repo_data"),
                    call_depth_reports=ctx["call_depth_reports"],
                ),
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
        lambda ctx: _isolate_agent_failure(CodeKey.DRY, file_path, lambda: run_dry(agents_container, prepared_file))
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
