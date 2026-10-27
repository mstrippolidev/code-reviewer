import httpx

from mcp_server.app import mcp
from mcp_server.config import get_mcp_settings
from mcp_server.repo_status import HttpRepoStatusSource, RepoStatusTools

API_TIMEOUT_SECONDS = 10.0


def ping(message: str) -> str:
    """Echo a message back with a pong prefix.

    Use this to check that the code-reviewer server is reachable. It has no
    side effects and costs nothing.

    Args:
        message: Any text to echo back.
    """
    return f"pong: {message}"


def _build_api_client() -> httpx.AsyncClient:
    settings = get_mcp_settings()
    return httpx.AsyncClient(
        base_url=settings.mcp_api_base_url,
        headers={"Authorization": f"Bearer {settings.mcp_api_access_token}"},
        timeout=API_TIMEOUT_SECONDS,
    )


mcp.add_tool(ping)
mcp.add_tool(RepoStatusTools(HttpRepoStatusSource(_build_api_client())).get_repo_status)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
