"""
    The one definition of when a repo is ready to be searched or reviewed, shared by every tool that needs an index.
"""
from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.tools.repo_status import (
    HttpRepoStatusSource,
    RepoNotFound,
    RepoSnapshot,
    RepoState,
    RepoStatus,
    RepoStatusUnavailable,
)


async def require_ready_repo(status_source: HttpRepoStatusSource, repo: str, tool_name: str) -> RepoSnapshot:
    """Returns the repo's snapshot if it is `ready`; otherwise raises a ToolError naming the call to make next.

    `tool_name` is the tool the LLM was using, so the error can tell it to call that tool again.
    """
    try:
        snapshot = await status_source.fetch_snapshot(repo)
    except RepoNotFound as error:
        raise ToolError(
            f"Repo '{repo}' is not registered. Call index_repo with its owner/name to register and index it."
        ) from error
    except RepoStatusUnavailable as error:
        raise ToolError(str(error)) from error
    if snapshot.status.state != RepoState.READY:
        raise ToolError(_not_ready_message(repo, snapshot.status, tool_name))
    return snapshot


def _not_ready_message(repo: str, status: RepoStatus, tool_name: str) -> str:
    """What to do next for a repo that is indexing, failed, or not indexed yet."""
    if status.state == RepoState.INDEXING:
        return (
            f"Repo '{repo}' is still being indexed ({status.files_indexed} of {status.files_total} files). "
            f"Call get_repo_status until its state is ready, then call {tool_name} again."
        )
    if status.state == RepoState.FAILED:
        outcome = f"finished with {status.files_failed} failed file(s)" if status.files_failed else "failed"
        return (
            f"Indexing of '{repo}' {outcome}, so a review would rest on an incomplete index. "
            "Ask the user to retry indexing from the web app, then call get_repo_status "
            "until its state is ready."
        )
    return (
        f"Repo '{repo}' is {status.state.value}. Call index_repo with its owner/name, then call "
        f"get_repo_status until its state is ready, then call {tool_name}."
    )
