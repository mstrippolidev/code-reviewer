"""
    Main file that will run the pipeline on a PR submission.
    It orchestrates the intake screen, file selection, and per-file pipeline run and
    call the agents for each.
"""
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.guardrails.errors import IntakeRejectedError
from code_reviewer.guardrails.intake_screen import run_intake_screen
from code_reviewer.pipeline.dispatch import review_file_runnable
from code_reviewer.pipeline.errors import FileTooLargeError, SubmissionTooLargeError
from code_reviewer.pipeline.file_size import run_file_size_guard
from code_reviewer.pipeline.pr_file_selection import select_pr_files
from code_reviewer.pipeline.raw_character_guard import run_raw_character_guard
from code_reviewer.pipeline.test_file_pairing import pair_source_files_with_tests
from code_reviewer.schemas.review import AgentReviewEntry, SizeStatus, SkippedFile
from code_reviewer.schemas.submission import PreparedFile, SubmittedFile

_SKIP_REASONS = {
    SubmissionTooLargeError: "raw_character_limit_exceeded",
    FileTooLargeError: "file_too_large",
    IntakeRejectedError: "intake_rejected",
}


def review_submission(
    files: list[SubmittedFile], agents_container: AgentsContainer
) -> tuple[list[AgentReviewEntry], list[SkippedFile]]:
    """Runs the full pipeline end to end: guards, dispatch, per prepared
    file — the single entry point from a raw submission to agent results.

    Args:
        files: Every file in the submission, source and test alike.
        agents_container: The complete set of built agents, grouped for
            dispatch. Built once by the caller and reused across requests.

    Returns:
        Every AgentReviewEntry produced across every prepared file, and
        every file skipped along the way with its reason.
    """
    prepared_files, skipped_files = prepare_files_for_pipeline(files)
    entries = [
        entry
        for prepared_file in prepared_files
        for entry in review_file_runnable(prepared_file, agents_container)
    ]
    return entries, skipped_files


def prepare_files_for_pipeline(files: list[SubmittedFile]) -> tuple[list[PreparedFile], list[SkippedFile]]:
    """Runs PR selection, test pairing, and the per-file guards, returning
    every file that's ready for agent dispatch.

    Args:
        files: Every file in the submission, source and test alike.

    Returns:
        Files that passed every guard, paired with their screened test files
        and SizeStatus; and every file skipped along the way, source or
        test, each with a reason.
    """
    selected_files, skipped_files, test_files = select_pr_files(files)
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
            ))

    return prepared_files, skipped_files

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
