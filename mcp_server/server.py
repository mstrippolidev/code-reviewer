from mcp.types import ToolAnnotations

from mcp_server.api_client import build_api_client
from mcp_server.app import mcp
from mcp_server.custom_caller_auth import CallerBearerAuth
from mcp_server.resources.agents import AGENTS_URI, AgentsResource
from mcp_server.tools.index_repo import IndexRepoTool
from mcp_server.tools.repo_status import HttpRepoStatusSource, RepoStatusTools
from mcp_server.tools.review import ReviewTools


def ping(message: str) -> str:
    """Echo a message back with a pong prefix.

    Use this to check that the code-reviewer server is reachable. It has no
    side effects and costs nothing.

    Args:
        message: Any text to echo back.
    """
    return f"pong: {message}"


mcp.add_tool(ping)
api_client = build_api_client(auth=CallerBearerAuth())
status_source = HttpRepoStatusSource(api_client)

mcp.add_tool(RepoStatusTools(status_source).get_repo_status)
mcp.add_tool(
    IndexRepoTool(api_client, status_source).index_repo,
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True),
)
review_tools = ReviewTools(api_client, status_source)
mcp.add_tool(
    review_tools.get_review,
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
mcp.add_tool(
    review_tools.review_repo_files,
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False),
)
mcp.add_tool(
    review_tools.review_code,
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False),
)
mcp.resource(
    AGENTS_URI,
    name="agents",
    title="Review agents",
    description=(
        "The review agents and what each one checks: code_key, name, weight, category, summary and checks. "
        "Read it before choosing an `agents` subset for a review, and use only the code_key values listed here. "
        "Fewer agents is cheaper and faster, so select only what the user asked about. "
        "The review's overall rating and recommendation come only from the agents that ran. "
        "DRY compares against a registered repo's indexed history, so a review with no repo skips it, "
        "and ARCH, COUP and TCASE then run without their cross-file evidence and repo-wide test lookup."
    ),
    mime_type="application/json",
)(AgentsResource(api_client).read_agents)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8001)
