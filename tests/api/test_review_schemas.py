"""
    Tests for ReviewRequestedMessage's repo-vs-guest shape rule and GuestReviewSubmissionRequest's limits.
"""
import uuid

import pytest
from pydantic import ValidationError

from api.schemas.reviews import GuestReviewSubmissionRequest, GuestSubmittedFile, ReviewRequestedMessage


def _guest_file(file_path: str = "a.py") -> GuestSubmittedFile:
    return GuestSubmittedFile(file_path=file_path, content="x = 1\n")


def test_repo_review_message_is_not_a_guest_review() -> None:
    message = ReviewRequestedMessage(
        review_id=uuid.uuid4(), file_paths=["a.py"], repo_id=10, owner_id=99, requested_by_user_id=1
    )

    assert message.is_guest_review is False


def test_guest_review_message_is_a_guest_review() -> None:
    message = ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], guest_session_id=7)

    assert message.is_guest_review is True


def test_message_with_neither_repo_nor_guest_fields_is_rejected() -> None:
    """Verify a message the consumer couldn't load files for never makes it onto the topic."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"])


def test_message_with_both_repo_and_guest_fields_is_rejected() -> None:
    """Verify the consumer is never left guessing which branch a message belongs to."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(
            review_id=uuid.uuid4(),
            file_paths=["a.py"],
            repo_id=10,
            owner_id=99,
            requested_by_user_id=1,
            guest_session_id=7,
        )


def test_guest_submission_over_five_files_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GuestReviewSubmissionRequest(files=[_guest_file(f"f{index}.py") for index in range(6)])


def test_guest_submission_with_duplicate_file_paths_is_rejected() -> None:
    """Verify two files can't collide on the same path, which keys every per-file result downstream."""
    with pytest.raises(ValidationError):
        GuestReviewSubmissionRequest(files=[_guest_file("a.py"), _guest_file("a.py")])
