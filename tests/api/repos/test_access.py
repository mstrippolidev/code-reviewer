"""
    Tests for RepoAccessChecker against a fake GitHub client and a fake Redis: no network, no real Redis.
"""
from collections.abc import AsyncIterator

import pytest
from cryptography.fernet import Fernet

from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user import User
from redis.exceptions import ConnectionError as RedisConnectionError

from api.integrations.github import GitHubAccessCheckError, GitHubTokenRejectedError
from api.repos.access import REPO_ACCESS_CACHE_TTL_SECONDS, RepoAccessChecker
from api.repos.errors import GitHubAuthorizationExpiredError, GitHubVerificationUnavailableError, RepoNotFoundError
from api.security.token_cipher import TokenCipher, TokenDecryptionError

CIPHER = TokenCipher(encryption_key=Fernet.generate_key().decode())


class FakeGitHub:
    def __init__(self, *, has_access: bool = True, error: Exception | None = None) -> None:
        self._has_access = has_access
        self._error = error
        self.calls = 0
        self.access_tokens: list[str] = []
        self.full_names: list[str] = []

    async def user_have_access(self, access_token: str, full_name: str) -> bool:
        self.calls += 1
        self.access_tokens.append(access_token)
        self.full_names.append(full_name)
        if self._error:
            raise self._error
        return self._has_access


class FakeRedis:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def exists(self, key: str) -> int:
        if self._error:
            raise self._error
        return int(key in self.values)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex

    async def scan_iter(self, match: str) -> AsyncIterator[str]:
        for key in list(self.values):
            if key.startswith(match.rstrip("*")):
                yield key

    async def delete(self, *keys: str) -> None:
        if not keys:
            raise ValueError("DEL needs at least one key")
        for key in keys:
            self.values.pop(key, None)


def _user(user_id: int = 1) -> User:
    return User(id=user_id, encrypted_github_token=CIPHER.encrypt("gho_token"))


def _repo(repo_id: int = 10) -> RegisteredRepo:
    return RegisteredRepo(repo_id=repo_id, full_name=f"octocat/repo-{repo_id}")


def _checker(github: FakeGitHub, redis: FakeRedis) -> RepoAccessChecker:
    return RepoAccessChecker(github, CIPHER, redis)


@pytest.mark.asyncio
async def test_require_access_remembers_a_granted_answer() -> None:
    """Verify that a confirmed user is cached so the next request skips GitHub."""
    redis = FakeRedis()

    await _checker(FakeGitHub(), redis).require_access(_user(), _repo())

    assert "repo_access:1:10" in redis.values


@pytest.mark.asyncio
async def test_require_access_caches_the_grant_for_the_configured_ttl() -> None:
    """Verify that the cached grant expires on its own, so lost GitHub access stops working."""
    redis = FakeRedis()

    await _checker(FakeGitHub(), redis).require_access(_user(), _repo())

    assert redis.ttls["repo_access:1:10"] == REPO_ACCESS_CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_require_access_skips_github_when_the_grant_is_cached() -> None:
    """Verify that a repeated request inside the cache window costs no GitHub call."""
    github = FakeGitHub()
    checker = _checker(github, FakeRedis())
    await checker.require_access(_user(), _repo())

    await checker.require_access(_user(), _repo())

    assert github.calls == 1


@pytest.mark.asyncio
async def test_require_access_raises_not_found_when_github_denies_the_user() -> None:
    """Verify that a denied user sees the same 404 as an unregistered repo."""
    with pytest.raises(RepoNotFoundError):
        await _checker(FakeGitHub(has_access=False), FakeRedis()).require_access(_user(), _repo())


@pytest.mark.asyncio
async def test_require_access_does_not_cache_a_denial() -> None:
    """Verify that a user who is granted access on GitHub is not locked out by a stale denial."""
    redis = FakeRedis()

    with pytest.raises(RepoNotFoundError):
        await _checker(FakeGitHub(has_access=False), redis).require_access(_user(), _repo())

    assert redis.values == {}


@pytest.mark.asyncio
async def test_require_access_raises_authorization_expired_when_the_token_is_rejected() -> None:
    """Verify that a revoked GitHub token tells the user to log in again."""
    github = FakeGitHub(error=GitHubTokenRejectedError("revoked"))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await _checker(github, FakeRedis()).require_access(_user(), _repo())


@pytest.mark.asyncio
async def test_require_access_forgets_every_grant_of_a_user_whose_token_is_rejected() -> None:
    """Verify that a revoked token cannot keep opening repos through cached grants."""
    redis = FakeRedis()
    await _checker(FakeGitHub(), redis).require_access(_user(), _repo(11))
    rejecting = FakeGitHub(error=GitHubTokenRejectedError("revoked"))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await _checker(rejecting, redis).require_access(_user(), _repo(12))

    assert "repo_access:1:11" not in redis.values


@pytest.mark.asyncio
async def test_require_access_keeps_the_grants_of_other_users_when_one_token_is_rejected() -> None:
    """Verify that one user's revoked token does not log everyone else out of their cached repos."""
    redis = FakeRedis()
    await _checker(FakeGitHub(), redis).require_access(_user(2), _repo(11))
    rejecting = FakeGitHub(error=GitHubTokenRejectedError("revoked"))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await _checker(rejecting, redis).require_access(_user(1), _repo(12))

    assert "repo_access:2:11" in redis.values


@pytest.mark.asyncio
async def test_require_access_raises_unavailable_when_github_cannot_answer() -> None:
    """Verify that a GitHub outage is reported as a bad gateway, not as a denied user."""
    github = FakeGitHub(error=GitHubAccessCheckError("down"))

    with pytest.raises(GitHubVerificationUnavailableError):
        await _checker(github, FakeRedis()).require_access(_user(), _repo())


@pytest.mark.asyncio
async def test_require_access_asks_github_with_the_decrypted_token() -> None:
    """Verify that GitHub is asked as the user, with their plaintext token and not the stored ciphertext."""
    github = FakeGitHub()

    await _checker(github, FakeRedis()).require_access(_user(), _repo())

    assert github.access_tokens == ["gho_token"]


@pytest.mark.asyncio
async def test_require_access_asks_github_about_the_registered_full_name() -> None:
    """Verify that the repo checked is the one stored at registration, not anything the caller supplied."""
    github = FakeGitHub()

    await _checker(github, FakeRedis()).require_access(_user(), _repo(10))

    assert github.full_names == ["octocat/repo-10"]


@pytest.mark.asyncio
async def test_require_access_does_not_share_a_grant_between_users() -> None:
    """Verify that one user's confirmed access never lets another user in on the same repo."""
    github = FakeGitHub()
    checker = _checker(github, FakeRedis())
    await checker.require_access(_user(1), _repo())

    await checker.require_access(_user(2), _repo())

    assert github.calls == 2


@pytest.mark.asyncio
async def test_require_access_does_not_share_a_grant_between_repos() -> None:
    """Verify that access to one repo says nothing about another repo of the same user."""
    github = FakeGitHub()
    checker = _checker(github, FakeRedis())
    await checker.require_access(_user(), _repo(10))

    await checker.require_access(_user(), _repo(11))

    assert github.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("repo_id", [1, 765693665, 2**53])
async def test_require_access_keys_the_grant_by_the_exact_repo_id(repo_id: int) -> None:
    """Verify that small, real-world and very large GitHub repo ids all produce an exact cache key."""
    redis = FakeRedis()

    await _checker(FakeGitHub(), redis).require_access(_user(), _repo(repo_id))

    assert f"repo_access:1:{repo_id}" in redis.values


@pytest.mark.asyncio
async def test_require_access_keeps_grants_of_a_user_whose_id_starts_with_the_rejected_users_id() -> None:
    """Verify that clearing user 1's grants does not also clear user 10's, whose key shares the digit."""
    redis = FakeRedis()
    await _checker(FakeGitHub(), redis).require_access(_user(10), _repo(11))
    rejecting = FakeGitHub(error=GitHubTokenRejectedError("revoked"))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await _checker(rejecting, redis).require_access(_user(1), _repo(12))

    assert "repo_access:10:11" in redis.values


@pytest.mark.asyncio
async def test_require_access_does_not_cache_anything_when_the_token_is_rejected() -> None:
    """Verify that a rejected token leaves no grant behind for the repo that was asked about."""
    redis = FakeRedis()
    rejecting = FakeGitHub(error=GitHubTokenRejectedError("revoked"))

    with pytest.raises(GitHubAuthorizationExpiredError):
        await _checker(rejecting, redis).require_access(_user(), _repo())

    assert redis.values == {}


@pytest.mark.asyncio
async def test_require_access_does_not_cache_anything_when_github_is_unavailable() -> None:
    """Verify that an outage is not remembered as either a grant or a denial."""
    redis = FakeRedis()
    unavailable = FakeGitHub(error=GitHubAccessCheckError("down"))

    with pytest.raises(GitHubVerificationUnavailableError):
        await _checker(unavailable, redis).require_access(_user(), _repo())

    assert redis.values == {}


@pytest.mark.asyncio
async def test_require_access_recovers_once_github_is_reachable_again() -> None:
    """Verify that a failed check does not poison later requests from the same user for the same repo."""
    redis = FakeRedis()
    with pytest.raises(GitHubVerificationUnavailableError):
        await _checker(FakeGitHub(error=GitHubAccessCheckError("down")), redis).require_access(_user(), _repo())

    await _checker(FakeGitHub(), redis).require_access(_user(), _repo())

    assert "repo_access:1:10" in redis.values


@pytest.mark.asyncio
async def test_require_access_raises_when_the_stored_token_cannot_be_decrypted() -> None:
    """Verify that a corrupted stored token is an error, not a silent denial."""
    user = User(id=1, encrypted_github_token="not-a-fernet-token")

    with pytest.raises(TokenDecryptionError):
        await _checker(FakeGitHub(), FakeRedis()).require_access(user, _repo())


@pytest.mark.asyncio
async def test_require_access_does_not_call_github_when_the_stored_token_cannot_be_decrypted() -> None:
    """Verify that no request goes to GitHub with a token that was never recovered."""
    github = FakeGitHub()
    user = User(id=1, encrypted_github_token="not-a-fernet-token")

    with pytest.raises(TokenDecryptionError):
        await _checker(github, FakeRedis()).require_access(user, _repo())

    assert github.calls == 0


@pytest.mark.asyncio
async def test_require_access_fails_closed_when_redis_is_down() -> None:
    """Verify that a cache outage raises instead of letting a user through unchecked."""
    redis = FakeRedis(error=RedisConnectionError("redis is down"))

    with pytest.raises(RedisConnectionError):
        await _checker(FakeGitHub(), redis).require_access(_user(), _repo())


@pytest.mark.asyncio
async def test_require_access_does_not_ask_github_when_redis_is_down() -> None:
    """Verify that the cache failure stops the request before it spends a GitHub call."""
    github = FakeGitHub()
    redis = FakeRedis(error=RedisConnectionError("redis is down"))

    with pytest.raises(RedisConnectionError):
        await _checker(github, redis).require_access(_user(), _repo())

    assert github.calls == 0
