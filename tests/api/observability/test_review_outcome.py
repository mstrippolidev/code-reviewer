"""
    Tests for the pure derivations behind the review lifecycle metrics: a message's kind and a report's shape.
"""
import uuid

from api.observability.review_outcome import ReviewKind, review_kind_of, summarize_review
from api.schemas.reviews import ReviewRequestedMessage
from code_reviewer.pipeline.orchestrator import AGENT_EXECUTION_FAILED_REASON, GUARD_EXECUTION_FAILED_REASON
from code_reviewer.schemas.review import CodeKey, SizeStatus, SkippedFile
from tests.api.review.test_review_consumer import (
    _make_agent_entry,
    _make_guest_message,
    _make_message,
    _make_result,
)


def _file_entry(file_path: str, size_status: SizeStatus = SizeStatus.NORMAL):
    entry = _make_agent_entry(file_path=file_path, agents_failed=[])
    return entry.model_copy(update={"size_status": size_status})


def test_a_message_with_a_repo_and_no_pull_request_is_a_repo_review() -> None:
    """Verify the ordinary registered-repo shape maps to the repo kind."""
    assert review_kind_of(_make_message()) == ReviewKind.REPO


def test_a_message_with_a_pull_request_number_is_a_pull_request_review() -> None:
    """Verify pr_number is what makes a repo-scoped message a pull request review."""
    assert review_kind_of(_make_message(pr_number=5)) == ReviewKind.PULL_REQUEST


def test_a_message_with_a_guest_session_is_a_guest_review() -> None:
    """Verify a guest session id maps to the guest kind."""
    assert review_kind_of(_make_guest_message()) == ReviewKind.GUEST


def test_a_message_with_only_a_user_is_a_repoless_review() -> None:
    """Verify a logged-in user's upload with no repo maps to the repoless kind."""
    message = ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], requested_by_user_id=1)

    assert review_kind_of(message) == ReviewKind.REPOLESS


def test_the_file_count_is_the_number_of_reviewed_files() -> None:
    """Verify every entry in the report's review list counts as one file."""
    result = _make_result(review=[_file_entry("a.py"), _file_entry("b.py")])

    assert summarize_review(result).file_count == 2


def test_files_are_counted_per_size_status() -> None:
    """Verify the size mix reports each status once per file that has it."""
    result = _make_result(
        review=[_file_entry("a.py"), _file_entry("b.py"), _file_entry("c.py", SizeStatus.SOFT_LIMIT)]
    )

    assert summarize_review(result).size_status_counts == {"normal": 2, "soft_limit": 1}


def test_a_file_skipped_on_an_unexpected_failure_counts_as_failed() -> None:
    """Verify both unexpected skip reasons are counted as files lost to a failure."""
    skipped = [
        SkippedFile(file_path="a.py", reason=AGENT_EXECUTION_FAILED_REASON),
        SkippedFile(file_path="b.py", reason=GUARD_EXECUTION_FAILED_REASON),
    ]

    assert summarize_review(_make_result(skipped_files=skipped)).failed_file_count == 2


def test_a_file_skipped_for_an_expected_reason_does_not_count_as_failed() -> None:
    """Verify a file left out by the PR file cap is a deliberate skip, not a failure."""
    skipped = [SkippedFile(file_path="a.py", reason="exceeded_pr_file_cap")]

    assert summarize_review(_make_result(skipped_files=skipped)).failed_file_count == 0


def test_a_report_with_no_files_has_an_empty_size_mix() -> None:
    """Verify an empty report summarizes to zeros instead of raising."""
    outcome = summarize_review(_make_result())

    assert (outcome.file_count, outcome.size_status_counts) == (0, {})


def test_agent_failures_inside_a_file_are_not_counted_as_lost_files() -> None:
    """Verify a file whose agents failed is still a reviewed file; only a skipped file is lost."""
    failed_agents = _make_agent_entry(file_path="a.py", agents_failed=[CodeKey.SOLID1])

    outcome = summarize_review(_make_result(review=[failed_agents]))

    assert (outcome.file_count, outcome.failed_file_count) == (1, 0)
