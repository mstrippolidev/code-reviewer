"""
    Tests for RepoGitHubVerifier against fakes: no real GitHub calls, no real encryption.
"""
import pytest

from api.db.models.user import User
from api.integrations.github import GitHubCommitFetchError, GitHubRepo, GitHubRepoFetchError
from api.repos.errors import (
    BranchNotFoundError,
    GitHubVerificationUnavailableError,
    InsufficientPythonError,
    RepoIdMismatchError,
)
from api.repos.github_verifier import RepoGitHubVerifier
from api.schemas.repos import RegisterRepoRequest


class FakeDecryptor:
    def decrypt(self, encrypted_token: str) -> str:
        return f"decrypted:{encrypted_token}"


class FakeGitHubClient:
    def __init__(
        self,
        *,
        repo: GitHubRepo | None = None,
        fetch_error: Exception | None = None,
        branch_error: Exception | None = None,
    ) -> None:
        self._repo = repo
        self._fetch_error = fetch_error
        self._branch_error = branch_error
        self.fetched_with_tokens: list[str] = []
        self.checked_branches: list[tuple[str, str, str]] = []

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        self.fetched_with_tokens.append(access_token)
        if self._fetch_error:
            raise self._fetch_error
        return self._repo

    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str:
        self.checked_branches.append((full_name, ref, access_token))
        if self._branch_error:
            raise self._branch_error
        return "def456"


def _make_user() -> User:
    return User(
        id=1,
        github_id=1,
        github_username="octocat",
        email=None,
        avatar_url=None,
        encrypted_github_token="cipher-text",
        github_granted_scopes="repo",
    )


def _make_github_repo(**overrides) -> GitHubRepo:
    defaults = {
        "repo_id": 10,
        "owner_id": 99,
        "full_name": "octocat/hello-world",
        "private": False,
        "default_branch": "main",
        "language": "Python",
        "python_percentage": 90.0,
        "has_enough_python": True,
    }
    defaults.update(overrides)
    return GitHubRepo(**defaults)


def _make_request(**overrides) -> RegisterRepoRequest:
    defaults = {"repo_id": 10, "full_name": "octocat/hello-world"}
    defaults.update(overrides)
    return RegisterRepoRequest(**defaults)


@pytest.mark.asyncio
async def test_verify_registration_returns_the_repo_github_confirmed() -> None:
    """Verify that the caller receives GitHub's own record, not the client's claim."""
    github_repo = _make_github_repo()
    verifier = RepoGitHubVerifier(FakeGitHubClient(repo=github_repo), FakeDecryptor())

    verified = await verifier.verify_registration(_make_request(), _make_user())

    assert verified is github_repo


@pytest.mark.asyncio
async def test_verify_registration_queries_github_with_the_users_decrypted_token() -> None:
    """Verify that GitHub is asked with the registering user's own token.

    That is what makes a repo the user cannot see fail instead of being trusted.
    """
    client = FakeGitHubClient(repo=_make_github_repo())
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    await verifier.verify_registration(_make_request(), _make_user())

    assert client.fetched_with_tokens == ["decrypted:cipher-text"]


@pytest.mark.asyncio
async def test_verify_registration_reports_github_being_unreachable() -> None:
    """Verify that a GitHub failure is raised with a client-safe message, not leaked."""
    client = FakeGitHubClient(fetch_error=GitHubRepoFetchError("503 from api.github.com"))
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    with pytest.raises(GitHubVerificationUnavailableError, match="Could not verify this repo with GitHub"):
        await verifier.verify_registration(_make_request(), _make_user())


@pytest.mark.asyncio
async def test_verify_registration_rejects_a_repo_id_that_does_not_match_the_name() -> None:
    """Verify that a client cannot register one repo's name under another repo's id."""
    client = FakeGitHubClient(repo=_make_github_repo(repo_id=999))
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    with pytest.raises(RepoIdMismatchError, match="repo_id does not match full_name"):
        await verifier.verify_registration(_make_request(repo_id=10), _make_user())


@pytest.mark.asyncio
async def test_verify_registration_rejects_a_repo_with_too_little_python() -> None:
    """Verify that the rejection names the repo's actual Python share."""
    client = FakeGitHubClient(repo=_make_github_repo(python_percentage=12.5, has_enough_python=False))
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    with pytest.raises(InsufficientPythonError, match="only 12.5% Python"):
        await verifier.verify_registration(_make_request(), _make_user())


@pytest.mark.asyncio
async def test_verify_registration_checks_the_id_before_the_python_share() -> None:
    """Verify the order of checks: a mismatched id is reported even when Python share is also too low."""
    client = FakeGitHubClient(repo=_make_github_repo(repo_id=999, has_enough_python=False))
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    with pytest.raises(RepoIdMismatchError):
        await verifier.verify_registration(_make_request(repo_id=10), _make_user())


@pytest.mark.asyncio
async def test_verify_branch_exists_checks_the_branch_with_the_users_decrypted_token() -> None:
    """Verify that the branch lookup targets the right repo, branch and credentials."""
    client = FakeGitHubClient()
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    await verifier.verify_branch_exists("octocat/hello-world", "dev", _make_user())

    assert client.checked_branches == [("octocat/hello-world", "dev", "decrypted:cipher-text")]


@pytest.mark.asyncio
async def test_verify_branch_exists_names_the_missing_branch() -> None:
    """Verify that a missing branch is reported by name so the caller can correct it."""
    client = FakeGitHubClient(branch_error=GitHubCommitFetchError("404"))
    verifier = RepoGitHubVerifier(client, FakeDecryptor())

    with pytest.raises(BranchNotFoundError, match="Branch 'ghost' was not found"):
        await verifier.verify_branch_exists("octocat/hello-world", "ghost", _make_user())
