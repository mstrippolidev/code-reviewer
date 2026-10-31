from enum import Enum
from http import HTTPStatus
from typing import Annotated, Any, Protocol

from httpx import AsyncClient, HTTPError, HTTPStatusError
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

REPO_BY_NAME_PATH = "/api/repos/name"
FILE_INDEXED = "indexed"
FILE_FAILED = "failed"
API_COMPLETED = "completed"

class RepoNotFound(Exception):
    """Raised when a repo is not registered for the caller."""


class RepoStatusUnavailable(Exception):
    """Raised when the repo's status cannot be read from api/."""


class RepoState(str, Enum):
    """Where a repo stands in the indexing lifecycle."""

    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    READY = "ready"
    STALE = "stale"
    FAILED = "failed"


class RepoStatus(BaseModel):
    """Snapshot of a repo's index returned to the calling LLM."""

    state: RepoState
    files_total: Annotated[int, Field(ge=0)]
    files_indexed: Annotated[int, Field(ge=0)]
    files_failed: Annotated[int, Field(ge=0)]
    indexed_commit: str | None
    head_commit: str | None
    branch: str


class RepoSnapshot(BaseModel):
    """A repo's status together with the id api/ addresses it by, which is never shown to the calling LLM."""

    repo_id: int
    status: RepoStatus


API_STATUS_TO_STATE = {
    "pending": RepoState.NOT_INDEXED,
    "indexing": RepoState.INDEXING,
    "paused": RepoState.INDEXING,
    "completed": RepoState.READY,
    "failed": RepoState.FAILED,
}


class RepoStatusSource(Protocol):
    """Contract for anything that can report a repo's index status."""

    async def fetch(self, repo: str) -> RepoStatus: ...


class HttpRepoStatusSource:
    """Reads a repo's index status from api/'s `GET /api/repos/name`."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def fetch(self, repo: str) -> RepoStatus:
        return (await self.fetch_snapshot(repo)).status

    async def fetch_snapshot(self, repo: str) -> RepoSnapshot:
        params = {"full_name": repo, "with_files": True}
        try:
            response = await self._client.get(REPO_BY_NAME_PATH, params=params)
            response.raise_for_status()
        except HTTPStatusError as error:
            if error.response.status_code == HTTPStatus.NOT_FOUND:
                raise RepoNotFound(repo) from error
            raise RepoStatusUnavailable(
                f"api/ answered {error.response.status_code} for '{repo}'. Try again shortly."
            ) from error
        except HTTPError as error:
            raise RepoStatusUnavailable("api/ is unreachable. Try again shortly.") from error
        payload = response.json()
        return RepoSnapshot(repo_id=payload["repo"]["repo_id"], status=self._to_repo_status(payload))

    def _to_repo_status(self, payload: dict[str, Any]) -> RepoStatus:
        repo = payload["repo"]
        files = payload["files"]
        files_failed = self._count_files(files, FILE_FAILED)
        return RepoStatus(
            state=self._to_state(repo["status"], files_failed),
            files_total=repo["total_files_expected"] or len(files),
            files_indexed=self._count_files(files, FILE_INDEXED),
            files_failed=files_failed,
            indexed_commit=repo["commit_sha"],
            head_commit=None,
            branch=repo["branch"],
        )

    def _count_files(self, files: list[dict[str, Any]], status: str) -> int:
        return sum(1 for file in files if file["status"] == status)

    def _to_state(self, api_status: str, files_failed: int) -> RepoState:
        if api_status == API_COMPLETED and files_failed:
            return RepoState.FAILED
        return API_STATUS_TO_STATE[api_status]



class RepoStatusTools:
    """Exposes repo index status as an MCP tool."""

    def __init__(self, source: RepoStatusSource) -> None:
        self._source = source

    async def get_repo_status(self, repo: str) -> RepoStatus:
        """Report whether a repository is indexed and how far indexing has got.

        Free and read-only. Call it before find_similar_code or review_pr to
        confirm the repo is `ready`. If it is `not_indexed` or `stale`, call
        index_repo next; if `failed`, some files did not index and
        find_similar_code results would be incomplete.

        Args:
            repo: GitHub full name of the repo, in the form `owner/name`.
        """
        try:
            return await self._source.fetch(repo)
        except RepoNotFound as error:
            raise ToolError(
                f"Repo '{repo}' is not registered. Call index_repo with "
                "its owner/name to register and index it."
            ) from error
        except RepoStatusUnavailable as error:
            raise ToolError(str(error)) from error
