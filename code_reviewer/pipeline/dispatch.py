"""
    Dispatches one prepared file to every built agent, splitting chunk
    agents' work into per-function/class pieces once the file is too
    large for a single call.
"""
from langchain_core.runnables import RunnableLambda, RunnableParallel

from code_reviewer.agents.base import AgentBase, FileReviewMeta, FileSizeAwareAgentBase
from code_reviewer.agents.coverage_gap import CoverageGapAgent
from code_reviewer.agents.llm.middleware import PRIORITY_DISCOUNTS
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.config.settings import get_settings
from code_reviewer.pipeline.code_splitter.interface import CodeChunk, CodeSplitterInterface
from code_reviewer.pipeline.code_splitter.python import PythonCodeSplit
from code_reviewer.schemas.paired import Pairing
from code_reviewer.schemas.review import AgentOutput, AgentReviewEntry, CodeKey, Incident, Priority, SizeStatus
from code_reviewer.schemas.submission import PreparedFile

_CHUNKED_SIZE_STATUSES = (SizeStatus.SOFT_LIMIT, SizeStatus.HARD_LIMIT_EXCEEDED)


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
    entries = _run_file_agents(prepared_file, agents_container.file_agents)
    chunk_entries = _run_chunk_agents(prepared_file, agents_container.chunk_agents, splitter)
    _apply_cmplx_soft_limit_incident(chunk_entries, prepared_file)
    entries += chunk_entries
    entries.append(_run_tcase_agent(prepared_file, agents_container.tcase_agent))
    return entries


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
        incidents += _offset_incidents(results[i].review[0].incidents, chunks[i].start_line)
    return AgentReviewEntry(
        file_path=file_path,
        code_key=agent.get_agent_key(),
        incidents=incidents,
        rating=_rating_from_incidents(incidents),
    )


def _run_tcase_agent(prepared_file: PreparedFile, tcase_agent: CoverageGapAgent) -> AgentReviewEntry:
    """Runs TCASE once, whole-file, via its paired test-file content —
    never chunked, regardless of size band."""
    pairing = Pairing(source_file=prepared_file.source_file, test_files=prepared_file.test_files)
    content = pairing.get_content()
    return tcase_agent.execute_agent(content, prepared_file.source_file.file_path).review[0]


def _offset_incidents(incidents: list[Incident], start_line: int) -> list[Incident]:
    """Rewrites each incident's line_position from chunk-relative to
    file-absolute, using the chunk's own start_line in the real file."""
    return [
        incident.model_copy(update={"line_position": _offset_line_position(incident.line_position, start_line)})
        for incident in incidents
    ]


def _offset_line_position(line_position: str, start_line: int) -> str:
    try:
        chunk_start, chunk_end = _parse_line_range(line_position)
    except ValueError:
        return line_position
    file_offset = start_line - 1
    return f"{chunk_start + file_offset}-{chunk_end + file_offset}"


def _parse_line_range(line_position: str) -> tuple[int, int]:
    start_text, end_text = line_position.split("-")
    return int(start_text), int(end_text)


def _rating_from_incidents(incidents: list[Incident]) -> int:
    """Computes one rating over a merged incident list, using the same
    discount formula every individual agent call already applies."""
    rating = 100
    for incident in incidents:
        rating -= PRIORITY_DISCOUNTS[incident.priority]
    return max(rating, 0)


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
    cmplx_entry.rating = _rating_from_incidents(cmplx_entry.incidents)


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


def review_file_runnable(
    prepared_file: PreparedFile,
    agents_container: AgentsContainer,
    splitter: CodeSplitterInterface | None = None,
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

    Returns:
        One AgentReviewEntry per agent that reviewed this file.
    """
    splitter = splitter or PythonCodeSplit()
    pairing = Pairing(source_file=prepared_file.source_file, test_files=prepared_file.test_files)
    context = {
        "code": prepared_file.source_file.content,
        "file_path": prepared_file.source_file.file_path,
        "size_status": prepared_file.size_status,
        "repo_data": prepared_file.repo_data,
    }
    branches = (
        {agent.get_agent_key().value: _file_agent_branch(agent) for agent in agents_container.file_agents}
        | {agent.get_agent_key().value: _chunk_agent_branch(agent, splitter) for agent in agents_container.chunk_agents}
        | {"TCASE": _tcase_branch(agents_container.tcase_agent, pairing.get_content())}
    )
    config = {"max_concurrency": get_settings().max_dispatch_concurrency}
    results = RunnableParallel(branches).invoke(context, config=config)
    entries = _unpack_runnable_results(results)
    _apply_cmplx_soft_limit_incident(entries, prepared_file)
    return entries


def _file_agent_branch(agent: FileSizeAwareAgentBase) -> RunnableLambda:
    """Builds a branch that runs one file agent against the shared context."""
    return RunnableLambda(
        lambda ctx: agent.execute_agent(
            ctx["code"],
            ctx["file_path"],
            FileReviewMeta(size_status=ctx["size_status"], repo_data=ctx.get("repo_data")),
        )
    )


def _chunk_agent_branch(agent: AgentBase, splitter: CodeSplitterInterface) -> RunnableLambda:
    """Builds a branch that runs one chunk agent against the shared context."""
    return RunnableLambda(lambda ctx: _run_chunk_agent(agent, ctx, splitter))


def _tcase_branch(agent: CoverageGapAgent, pairing_content: str) -> RunnableLambda:
    """Builds a branch that runs TCASE against its own paired content,
    ignoring the shared context's raw source code."""
    return RunnableLambda(lambda ctx: agent.execute_agent(pairing_content, ctx["file_path"]))


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
