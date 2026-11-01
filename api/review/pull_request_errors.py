"""
    Refusals when a pull request is submitted for review; each message is written for the person who submitted it.
"""


class PullRequestNotFoundError(Exception):
    """Raised when GitHub has no such pull request, or the user cannot see it."""


class PullRequestNotOpenError(Exception):
    """Raised when the pull request is closed or already merged."""

    def __init__(self, number: int) -> None:
        super().__init__(f"Pull request {number} is not open, so it is not reviewed")


class PullRequestTooLargeError(Exception):
    """Raised when the pull request changes more files than a review accepts."""

    def __init__(self, changed_files: int, limit: int) -> None:
        super().__init__(f"This pull request changes {changed_files} files; at most {limit} can be reviewed")


class PullRequestBaseBranchError(Exception):
    """Raised when the pull request targets a branch other than the one the repo's index follows."""

    def __init__(self, base_branch: str, tracked_branch: str) -> None:
        super().__init__(
            f"This pull request targets '{base_branch}', but the repo's index follows '{tracked_branch}', "
            "so duplicates and cross-file evidence would be checked against the wrong code"
        )


class PullRequestRepoNotReadyError(Exception):
    """Raised when the repo's index failed or is paused, so a review cannot be queued behind it."""

    def __init__(self, status: str) -> None:
        super().__init__(
            f"This repo's indexing is {status}. Ask the person who registered it to resume or retry it "
            "from the web app, then submit the pull request again"
        )


class PullRequestUnavailableError(Exception):
    """Raised when GitHub cannot be reached or answers a pull request read unexpectedly."""


class PullRequestQueueError(Exception):
    """Raised when the review cannot be queued."""
