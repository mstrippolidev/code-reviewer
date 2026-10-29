from mcp_server.api_client import build_api_client
from mcp_server.app import mcp
from mcp_server.custom_caller_auth import CallerBearerAuth
from mcp_server.repo_status import HttpRepoStatusSource, RepoStatusTools


def ping(message: str) -> str:
    """Echo a message back with a pong prefix.

    Use this to check that the code-reviewer server is reachable. It has no
    side effects and costs nothing.

    Args:
        message: Any text to echo back.
    """
    return f"pong: {message}"


mcp.add_tool(ping)
mcp.add_tool(RepoStatusTools(HttpRepoStatusSource(build_api_client(auth=CallerBearerAuth()))).get_repo_status)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8001)
