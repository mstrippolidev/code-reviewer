from redis.asyncio import Redis

from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user import User
from api.integrations.github import GitHubAccessCheckError, GitHubOAuthClient, GitHubTokenRejectedError
from api.repos.errors import GitHubAuthorizationExpiredError, GitHubVerificationUnavailableError, RepoNotFoundError
from api.security.token_cipher import TokenCipher

REPO_ACCESS_CACHE_TTL_SECONDS = 300
CACHE_KEY_PREFIX = "repo_access"


class RepoAccessChecker:
    """Confirms with GitHub that a user can see a repo, caching a granted answer in Redis for a few minutes."""

    def __init__(self, github: GitHubOAuthClient, token_cipher: TokenCipher, redis: Redis) -> None:
        self._github = github
        self._token_cipher = token_cipher
        self._redis = redis

    async def require_access(self, user: User, repo: RegisteredRepo) -> None:
        if not await self.has_access(user, repo):
            raise RepoNotFoundError("Could not find the repo")

    async def has_access(self, user: User, repo: RegisteredRepo) -> bool:
        cache_key = f"{CACHE_KEY_PREFIX}:{user.id}:{repo.repo_id}"
        if await self._redis.exists(cache_key):
            return True
        if not await self._ask_github(user, repo):
            return False
        await self._redis.set(cache_key, "1", ex=REPO_ACCESS_CACHE_TTL_SECONDS)
        return True

    async def _ask_github(self, user: User, repo: RegisteredRepo) -> bool:
        access_token = self._token_cipher.decrypt(user.encrypted_github_token)
        try:
            return await self._github.user_have_access(access_token, repo.full_name)
        except GitHubTokenRejectedError as error:
            await self._forget_user(user.id)
            raise GitHubAuthorizationExpiredError("GitHub authorization expired, please log in again") from error
        except GitHubAccessCheckError as error:
            raise GitHubVerificationUnavailableError("Could not confirm your access to this repo with GitHub") from error

    async def _forget_user(self, user_id: int) -> None:
        keys = [key async for key in self._redis.scan_iter(match=f"{CACHE_KEY_PREFIX}:{user_id}:*")]
        if keys:
            await self._redis.delete(*keys)
