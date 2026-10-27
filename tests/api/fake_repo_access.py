from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user import User
from api.repos.errors import RepoNotFoundError


class FakeRepoAccessChecker:
    """Stands in for RepoAccessChecker in router tests: allows every repo unless built to deny or fail."""

    def __init__(self, *, denies: bool = False, error: Exception | None = None) -> None:
        self._denies = denies
        self._error = error
        self.calls: list[tuple[int, int]] = []

    async def require_access(self, user: User, repo: RegisteredRepo) -> None:
        if not await self.has_access(user, repo):
            raise RepoNotFoundError("Could not find the repo")

    async def has_access(self, user: User, repo: RegisteredRepo) -> bool:
        self.calls.append((user.id, repo.repo_id))
        if self._error:
            raise self._error
        return not self._denies
