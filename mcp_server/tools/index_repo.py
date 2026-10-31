"""
    Tool for indexing a repo.
"""
from http import HTTPStatus

from httpx import AsyncClient, HTTPError, HTTPStatusError, Response
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.tools.helper_api_error import detail_of, retry_after_hint
from mcp_server.tools.repo_status import RepoNotFound, RepoStatus, RepoStatusSource, RepoStatusUnavailable

REGISTER_REPO_PATH = "/api/repos"


class IndexRepoTool:
    """Exposes repo registration and indexing as an MCP tool."""

    def __init__(self, client: AsyncClient, status_source: RepoStatusSource) -> None:
        self._client = client
        self._status_source = status_source

    async def index_repo(self, repo_full_name: str, branch_name: str | None = None) -> RepoStatus:
        """Register a GitHub repository and start indexing it, or link it to your account if already indexed.

        Costs LLM and embedding spend, so call it once per repo, then poll
        get_repo_status until the state is `ready`. It returns immediately with
        a status snapshot and never waits for indexing to finish. Calling it
        again is safe: an already-indexed repo is not indexed twice.

        Args:
            repo_full_name: GitHub full name of the repo, in the form `owner/name`,
                for example `acme/billing-service`.
            branch_name: Branch to index. Omit it to use the repo's default branch.
                It only applies when the repo is first indexed or restarted
                after a failure; an already-indexed repo keeps its branch.
        """
        await self._start_indexing(repo_full_name, branch_name)
        return await self._read_status(repo_full_name)

    async def _start_indexing(self, repo_full_name: str, branch_name: str | None) -> None:
        body = {"full_name": repo_full_name, "branch": branch_name}
        try:
            response = await self._client.post(REGISTER_REPO_PATH, json=body)
            response.raise_for_status()
        except HTTPStatusError as error:
            raise self._to_tool_error(repo_full_name, error.response) from error
        except HTTPError as error:
            raise ToolError("api/ is unreachable. Try again shortly.") from error

    async def _read_status(self, repo_full_name: str) -> RepoStatus:
        try:
            return await self._status_source.fetch(repo_full_name)
        except (RepoNotFound, RepoStatusUnavailable) as error:
            raise ToolError(
                f"Repo '{repo_full_name}' was registered but its status could not be read. "
                "Call get_repo_status to check on it."
            ) from error

    def _to_tool_error(self, repo_full_name: str, response: Response) -> ToolError:
        if response.status_code == HTTPStatus.BAD_REQUEST:
            return ToolError(f"{detail_of(response)}. Correct the argument and call index_repo again.")
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            return ToolError(
                "Your GitHub authorization has expired. Ask the user to sign in again "
                "on the web app, then call index_repo again."
            )
        if response.status_code == HTTPStatus.NOT_FOUND:
            return ToolError(
                f"Repo '{repo_full_name}' was not found, or your GitHub account cannot access it. "
                "Check the owner/name spelling."
            )
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            return ToolError(self._too_many_requests_message(response))
        return ToolError(f"api/ answered {response.status_code}. Try again shortly.")

    def _too_many_requests_message(self, response: Response) -> str:
        return (
            f"{detail_of(response)}.{retry_after_hint(response)} "
            "Call get_repo_status to see which repos are still indexing."
        )
