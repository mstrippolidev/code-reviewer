class RepoAlreadyRegisteredError(Exception):
    """Raised when a repo is registered while an active registration for it exists."""

    def __init__(self) -> None:
        super().__init__("This repo is already registered")


class RepoNotFoundError(Exception):
    """Raised when no registered repo matches the requested name."""


class IndexedFileNotFoundError(Exception):
    """Raised when a registered repo has no indexed content for the requested file."""


class GitHubVerificationUnavailableError(Exception):
    """Raised when GitHub cannot confirm a repo's details."""


class GitHubAuthorizationExpiredError(Exception):
    """Raised when GitHub no longer accepts the user's token, so they must log in again."""


class RepoIdMismatchError(Exception):
    """Raised when the claimed repo_id does not belong to the claimed full_name."""


class InsufficientPythonError(Exception):
    """Raised when a repo contains too little Python to be reviewed."""


class BranchNotFoundError(Exception):
    """Raised when the requested branch does not exist on GitHub."""


class RepoEventPublishError(Exception):
    """Raised when a repo lifecycle event cannot be queued."""


class RepoPurgeError(Exception):
    """Raised when a repo's indexed content cannot be removed."""
