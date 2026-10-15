from typing import Protocol

from api.db.models.user import User
from api.integrations.github import (
    PYTHON_PERCENTAGE_THRESHOLD,
    GitHubCommitFetchError,
    GitHubRepo,
    GitHubRepoFetchError,
)
from api.repos.errors import (
    BranchNotFoundError,
    GitHubVerificationUnavailableError,
    InsufficientPythonError,
    RepoIdMismatchError,
)
from api.schemas.repos import RegisterRepoRequest


class RepoMetadataSource(Protocol):
    """Contract for anything that can look up a repo and its branches on GitHub."""

    async def fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo: ...

    async def fetch_branch_commit_sha(self, access_token: str, full_name: str, ref: str) -> str: ...


class TokenDecryptor(Protocol):
    """Contract for anything that can reveal a stored GitHub access token."""

    def decrypt(self, encrypted_token: str) -> str: ...


class RepoGitHubVerifier:
    """Confirms against GitHub, with the user's own token, that a repo or branch is real and reviewable."""

    def __init__(self, github_client: RepoMetadataSource, token_decryptor: TokenDecryptor) -> None:
        self._github_client = github_client
        self._token_decryptor = token_decryptor

    async def verify_registration(self, request: RegisterRepoRequest, user: User) -> GitHubRepo:
        access_token = self._token_decryptor.decrypt(user.encrypted_github_token)
        repo = await self._fetch_repo(access_token, request.full_name)
        self._ensure_id_matches(repo, request)
        self._ensure_enough_python(repo)
        return repo

    async def verify_branch_exists(self, full_name: str, branch: str, user: User) -> None:
        access_token = self._token_decryptor.decrypt(user.encrypted_github_token)
        try:
            await self._github_client.fetch_branch_commit_sha(access_token, full_name, branch)
        except GitHubCommitFetchError as error:
            raise BranchNotFoundError(f"Branch '{branch}' was not found") from error

    async def _fetch_repo(self, access_token: str, full_name: str) -> GitHubRepo:
        try:
            return await self._github_client.fetch_repo(access_token, full_name)
        except GitHubRepoFetchError as error:
            raise GitHubVerificationUnavailableError("Could not verify this repo with GitHub") from error

    def _ensure_id_matches(self, repo: GitHubRepo, request: RegisterRepoRequest) -> None:
        if repo.repo_id != request.repo_id:
            raise RepoIdMismatchError("repo_id does not match full_name")

    def _ensure_enough_python(self, repo: GitHubRepo) -> None:
        if not repo.has_enough_python:
            raise InsufficientPythonError(
                f"Repo is only {repo.python_percentage}% Python; must be at least {PYTHON_PERCENTAGE_THRESHOLD}%"
            )
