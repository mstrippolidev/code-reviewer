"""
    Tests for ReviewRequestedMessage's repo-vs-guest shape rule and GuestReviewSubmissionRequest's limits.
"""
import uuid

import pytest
from pydantic import ValidationError

from api.db.models.review_job import ReviewJob, ReviewJobStatus
from api.schemas.reviews import (
    FileData,
    GuestReviewSubmissionRequest,
    GuestSubmittedFile,
    RepolessReviewSubmissionRequest,
    ReviewJobRead,
    ReviewRequestedMessage,
    ReviewSubmissionRequest,
)
from code_reviewer.config.settings import get_settings
from code_reviewer.schemas.review import CodeKey


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


def test_submission_without_agents_selects_every_agent() -> None:
    """Verify that leaving agents out means no restriction, which the job stores as null."""
    request = ReviewSubmissionRequest(file_paths=["a.py"])

    assert request.agents is None


def test_submission_accepts_a_subset_of_known_agents() -> None:
    """Verify that agent keys given as strings are parsed into the CodeKey enum."""
    request = ReviewSubmissionRequest(file_paths=["a.py"], agents=["TEST", "TCASE"])

    assert request.agents == [CodeKey.TEST, CodeKey.TCASE]


def test_submission_with_an_unknown_agent_is_rejected_and_names_the_valid_keys() -> None:
    """Verify that a typo in an agent key fails with the list of valid keys, so a caller can correct it."""
    with pytest.raises(ValidationError, match="SOLID1"):
        ReviewSubmissionRequest(file_paths=["a.py"], agents=["NOPE"])


def test_submission_with_a_duplicate_agent_is_rejected() -> None:
    """Verify that listing one agent twice is an error instead of being silently deduplicated."""
    with pytest.raises(ValidationError):
        ReviewSubmissionRequest(file_paths=["a.py"], agents=["TEST", "TEST"])


def test_submission_with_an_empty_agent_list_is_rejected() -> None:
    """Verify that an empty list, which would review nothing, is refused rather than read as all agents."""
    with pytest.raises(ValidationError):
        ReviewSubmissionRequest(file_paths=["a.py"], agents=[])


def _file_data(file_path: str = "a.py") -> FileData:
    return FileData(file_path=file_path, content="x = 1\n")


def test_repoless_submission_keeps_each_files_path_and_content() -> None:
    """Verify that the content travels with the path, since there is no repo to fetch it from."""
    request = RepolessReviewSubmissionRequest(files=[_file_data()])

    assert (request.files[0].file_path, request.files[0].content) == ("a.py", "x = 1\n")


def test_repoless_submission_without_agents_selects_every_agent() -> None:
    """Verify that omitting agents means no restriction."""
    assert RepolessReviewSubmissionRequest(files=[_file_data()]).agents is None


def test_repoless_submission_with_no_files_is_rejected() -> None:
    """Verify that a review of nothing never reaches the queue."""
    with pytest.raises(ValidationError):
        RepolessReviewSubmissionRequest(files=[])


def test_repoless_submission_over_the_file_cap_is_rejected() -> None:
    """Verify that it is held to the same file cap as a repo review."""
    too_many = get_settings().max_files_per_submission + 1

    with pytest.raises(ValidationError):
        RepolessReviewSubmissionRequest(files=[_file_data(f"f{index}.py") for index in range(too_many)])


def test_repoless_submission_at_the_file_cap_is_accepted() -> None:
    """Verify that the cap is inclusive."""
    at_cap = get_settings().max_files_per_submission

    request = RepolessReviewSubmissionRequest(files=[_file_data(f"f{index}.py") for index in range(at_cap)])

    assert len(request.files) == at_cap


def test_repoless_submission_with_duplicate_file_paths_is_rejected() -> None:
    """Verify that two files cannot collide on one path, which keys every per-file result."""
    with pytest.raises(ValidationError):
        RepolessReviewSubmissionRequest(files=[_file_data("a.py"), _file_data("a.py")])


def test_repoless_submission_accepts_a_subset_of_agents() -> None:
    """Verify that agent keys given as strings are parsed into the CodeKey enum."""
    request = RepolessReviewSubmissionRequest(files=[_file_data()], agents=["TEST", "TCASE"])

    assert request.agents == [CodeKey.TEST, CodeKey.TCASE]


def test_repoless_submission_asking_for_dry_is_rejected_and_says_why() -> None:
    """Verify that DRY, which needs a repo's history, is refused with a reason the LLM can act on."""
    with pytest.raises(ValidationError, match="registered repo"):
        RepolessReviewSubmissionRequest(files=[_file_data()], agents=["DRY", "TEST"])


def test_repoless_submission_with_an_unknown_agent_is_rejected_and_names_the_valid_keys() -> None:
    """Verify that a typo in an agent key fails with the list of valid keys."""
    with pytest.raises(ValidationError, match="SOLID1"):
        RepolessReviewSubmissionRequest(files=[_file_data()], agents=["NOPE"])


def test_repoless_submission_with_a_duplicate_agent_is_rejected() -> None:
    """Verify that listing one agent twice is an error instead of being silently deduplicated."""
    with pytest.raises(ValidationError):
        RepolessReviewSubmissionRequest(files=[_file_data()], agents=["TEST", "TEST"])


def test_repoless_submission_with_an_empty_agent_list_is_rejected() -> None:
    """Verify that an empty list, which would review nothing, is refused rather than read as all agents."""
    with pytest.raises(ValidationError):
        RepolessReviewSubmissionRequest(files=[_file_data()], agents=[])


def test_user_repoless_review_message_is_accepted_and_has_uploaded_files() -> None:
    """Verify that a user with no repo and no guest session is a valid message shape whose files are stored."""
    message = ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], requested_by_user_id=1)

    assert message.has_uploaded_files is True


def test_user_repoless_review_message_is_not_a_guest_review() -> None:
    """Verify that the consumer is not told this is a guest's review."""
    message = ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], requested_by_user_id=1)

    assert message.is_guest_review is False


def test_repo_review_message_does_not_have_uploaded_files() -> None:
    """Verify that a repo review still loads its content from the index."""
    message = ReviewRequestedMessage(
        review_id=uuid.uuid4(), file_paths=["a.py"], repo_id=10, owner_id=99, requested_by_user_id=1
    )

    assert message.has_uploaded_files is False


def test_guest_review_message_has_uploaded_files() -> None:
    """Verify that a guest review keeps loading its stored raw files."""
    message = ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], guest_session_id=7)

    assert message.has_uploaded_files is True


def test_message_with_a_repo_but_no_owner_is_rejected() -> None:
    """Verify that a half-filled repo review is not mistaken for a repoless one."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=["a.py"], repo_id=10, requested_by_user_id=1)


def test_review_message_carries_the_requested_agents() -> None:
    """Verify that the Kafka message round-trips the agents the consumer must restrict to."""
    message = ReviewRequestedMessage(
        review_id=uuid.uuid4(), file_paths=["a.py"], repo_id=10, owner_id=99, requested_by_user_id=1, agents=["VAR"]
    )

    assert ReviewRequestedMessage.model_validate_json(message.model_dump_json()).agents == [CodeKey.VAR]


def _pull_request_message(**overrides) -> ReviewRequestedMessage:
    fields = {
        "review_id": uuid.uuid4(),
        "file_paths": [],
        "repo_id": 10,
        "owner_id": 99,
        "requested_by_user_id": 1,
        "pr_number": 7,
    }
    return ReviewRequestedMessage(**(fields | overrides))


def test_pull_request_review_message_is_accepted_with_no_file_paths_yet() -> None:
    """Verify the submit route can publish before the worker has read the pull request's files."""
    message = _pull_request_message()

    assert message.is_pull_request_review is True


def test_pull_request_review_message_is_not_loaded_from_uploaded_files() -> None:
    """Verify the consumer is not sent to the stored-files path, which has no repo to compare against."""
    message = _pull_request_message()

    assert message.has_uploaded_files is False


def test_repo_review_message_is_not_a_pull_request_review() -> None:
    """Verify an ordinary repo review keeps loading its files from the index."""
    message = ReviewRequestedMessage(
        review_id=uuid.uuid4(), file_paths=["a.py"], repo_id=10, owner_id=99, requested_by_user_id=1
    )

    assert message.is_pull_request_review is False


def test_pull_request_review_message_without_a_repo_is_rejected() -> None:
    """Verify a pull request number alone cannot be read as a repoless review."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=[], requested_by_user_id=1, pr_number=7)


def test_pull_request_review_message_without_a_requesting_user_is_rejected() -> None:
    """Verify the worker always knows whose GitHub token to read the files with."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=[], repo_id=10, owner_id=99, pr_number=7)


def test_guest_review_message_with_a_pull_request_number_is_rejected() -> None:
    """Verify a guest, who has no GitHub token, cannot be mixed with a pull request review."""
    with pytest.raises(ValidationError):
        ReviewRequestedMessage(review_id=uuid.uuid4(), file_paths=[], guest_session_id=7, pr_number=7)


def test_pull_request_review_message_round_trips_through_json() -> None:
    """Verify the Kafka message keeps the pull request number the worker needs."""
    message = _pull_request_message()

    assert ReviewRequestedMessage.model_validate_json(message.model_dump_json()).pr_number == 7


def test_review_job_read_exposes_the_pull_request_number_and_head_commit() -> None:
    """Verify a client can see which pull request, at which commit, a review covers."""
    job = ReviewJob(
        id=1,
        review_id=uuid.uuid4(),
        repo_id=10,
        requested_by_user_id=1,
        file_paths=[],
        pr_number=7,
        head_sha="abc123",
        status=ReviewJobStatus.PENDING,
        status_reason=None,
        result=None,
        agent_entries=None,
        agents=None,
    )

    read = ReviewJobRead.model_validate(job)

    assert (read.pr_number, read.head_sha) == (7, "abc123")
