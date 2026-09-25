"""
    Main file that will run the pipeline on a PR submission.
    It orchestrates the intake screen, file selection, and per-file pipeline run and
    call the agents for each.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.guardrails.intake_screen import run_intake_screen
from code_reviewer.pipeline.aggregator import Aggregator
from code_reviewer.pipeline.dispatch import review_file_runnable
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.pipeline.file_size import run_file_size_guard
from code_reviewer.pipeline.pr_file_selection import is_test_file, select_pr_files
from code_reviewer.pipeline.raw_character_guard import run_raw_character_guard
from code_reviewer.pipeline.test_file_pairing import pair_source_files_with_tests
from code_reviewer.rag.dry_evidence import attach_code, groups_for_file
from code_reviewer.rag.dry_matching import find_intra_pr_duplicates
from code_reviewer.rag.errors import DryMatchingChunkingError
from code_reviewer.rag.repo_data import RepoData
from code_reviewer.rag.structural_hash_store import LocatedChunk
from code_reviewer.schemas.review import (
    AgentReviewEntry,
    AggregatorOutput,
    CodeKey,
    ReviewScope,
    SizeStatus,
    SkippedFile,
)
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

logger = logging.getLogger(__name__)

_SKIP_REASONS = {
    SubmissionTooLargeError: "raw_character_limit_exceeded",
    FileTooLargeError: "file_too_large",
    IntakeRejectedError: "intake_rejected",
}
_AGENT_EXECUTION_FAILED_REASON = "agent_execution_failed"


async def run_pipeline(
    files: list[SubmittedFile],
    agents_container: AgentsContainer,
    repo_data: RepoData | None = None,
    on_file_reviewed: Callable[[str, bool, list[AgentReviewEntry]], Awaitable[None]] | None = None,
    on_agent_reviewed: Callable[[CodeKey, AgentReviewEntry], Awaitable[None]] | None = None,
) -> AggregatorOutput:
    """Runs the full pipeline end to end: guards, dispatch, aggregation —
    the single entry point from a raw submission to the final PR report.

    Args:
        files: Every file in the submission, source and test alike.
        agents_container: The complete set of built agents, grouped for
            dispatch. Built once by the caller and reused across requests.
        repo_data: Scoping for this submission's repo, shared by every file
            in it. None for a standalone review with no repo context, in
            which case ARCH/COUP's evidence hop falls back to single-file
            judgment.
        on_file_reviewed: Optional progress hook, awaited with a file's path,
            whether its dispatch raised, and every agent entry produced for
            it (empty on a raise), once that file is settled. Files are
            processed one at a time, in order, so this is safe to use for
            incremental progress reporting.
        on_agent_reviewed: Optional progress hook, awaited with one agent's
            code_key and its finished AgentReviewEntry the instant that
            agent finishes on the current file — other agents on that same
            file may still be running.

    Returns:
        The complete PR-level report: one merged entry per reviewed file,
        plus PR-level meta. A file whose dispatch raises (a provider outage,
        every retry exhausted) is treated like any other skip — reported in
        meta.skipped_files rather than failing every other file's review.
    """
    prepared_files, skipped_files = await asyncio.to_thread(prepare_files_for_pipeline, files, repo_data)
    entries = []
    reviewed_files = []
    for prepared_file in prepared_files:
        file_path = prepared_file.source_file.file_path
        try:
            file_entries = await review_file_runnable(
                prepared_file, agents_container, on_agent_reviewed=on_agent_reviewed
            )
        except Exception:
            logger.exception("Agent dispatch failed for file_path=%s; skipping it and continuing", file_path)
            skipped_files.append(SkippedFile(file_path=file_path, reason=_AGENT_EXECUTION_FAILED_REASON))
            if on_file_reviewed is not None:
                await on_file_reviewed(file_path, True, [])
            continue
        entries.extend(file_entries)
        reviewed_files.append(prepared_file)
        if on_file_reviewed is not None:
            await on_file_reviewed(file_path, False, file_entries)
    return Aggregator().build_output(entries, reviewed_files, skipped_files)


def prepare_files_for_pipeline(
    files: list[SubmittedFile], repo_data: RepoData | None = None
) -> tuple[list[PreparedFile], list[SkippedFile]]:
    """Runs PR selection, test pairing, and the per-file guards, returning
    every file that's ready for agent dispatch.

    Args:
        files: Every file in the submission, source and test alike.
        repo_data: Scoping for this submission's repo, stamped onto every
            resulting PreparedFile. None for a standalone review with no
            repo context.

    Returns:
        Files that passed every guard, paired with their screened test files
        and SizeStatus; and every file skipped along the way, source or
        test, each with a reason.
    """
    selected_files, skipped_files, test_files = select_pr_files(files)
    intra_pr_groups = _intra_pr_duplicate_groups(selected_files)
    pairings = pair_source_files_with_tests(selected_files, test_files)
    prepared_files = []

    for pairing in pairings:
        try:
            size_status = _run_source_file_guards(pairing.source_file.content)
        except (SubmissionTooLargeError, FileTooLargeError, IntakeRejectedError) as error:
            skipped_files.append(_skipped_file(pairing.source_file.file_path, error))
        else:
            screened_test_files, rejected_test_files = _screen_test_files(pairing.test_files)
            skipped_files.extend(rejected_test_files)
            prepared_files.append(PreparedFile(
                source_file=pairing.source_file,
                test_files=screened_test_files,
                size_status=size_status,
                review_scope=_review_scope(pairing.source_file.file_path),
                repo_data=repo_data,
                intra_pr_duplicates=groups_for_file(intra_pr_groups, pairing.source_file.file_path),
            ))

    return prepared_files, skipped_files

def _intra_pr_duplicate_groups(selected_files: list[SubmittedFile]) -> list[list[LocatedChunk]]:
    """Computed once for the whole PR rather than per file, since a
    duplicate group can span files a single file's own pipeline pass never
    otherwise sees together. Degrades to no evidence rather than failing
    the whole submission if any one file can't be chunked."""
    try:
        return attach_code(selected_files, find_intra_pr_duplicates(selected_files))
    except DryMatchingChunkingError:
        logger.warning("Skipping intra-PR duplicate detection: a file could not be chunked.")
        return []

def _review_scope(file_path: str) -> ReviewScope:
    """A test file only reaches this point as a review target when select_pr_files found no source to pair it with."""
    return ReviewScope.TEST_FILE_STANDALONE if is_test_file(file_path) else ReviewScope.FULL

def _run_source_file_guards(content: str) -> SizeStatus:
    """Runs the three per-file guards in cost-ascending order, returning
    the file's SizeStatus once all three pass."""
    run_raw_character_guard(content)
    size_status = run_file_size_guard(content)
    run_intake_screen(content)
    return size_status

def _skipped_file(file_path: str, error: Exception) -> SkippedFile:
    return SkippedFile(file_path=file_path, reason=_SKIP_REASONS[type(error)])

def _screen_test_files(test_files: list[SubmittedFile]) -> tuple[list[SubmittedFile], list[SkippedFile]]:
    """Screens each paired test file, keeping the ones that pass. A
    rejected test file drops out of the pairing rather than skipping the
    source file it belongs to."""
    screened, rejected = [], []
    for test_file in test_files:
        try:
            _run_test_file_guards(test_file.content)
        except (SubmissionTooLargeError, IntakeRejectedError) as error:
            rejected.append(_skipped_file(test_file.file_path, error))
        else:
            screened.append(test_file)
    return screened, rejected

def _run_test_file_guards(content: str) -> None:
    """Screens a paired test file the same way as a source file, minus the
    size guard — no agent is ever rated on a test file's size."""
    run_raw_character_guard(content)
    run_intake_screen(content)
