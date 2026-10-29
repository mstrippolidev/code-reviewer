"""
    Instance file that create the MCP component
"""
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings

from mcp_server.api_client import build_api_client
from mcp_server.config import get_mcp_settings
from mcp_server.custom_token_verification import ApiTokenVerifier

_settings = get_mcp_settings()

mcp = MCPServer(
    "Code-Review",
    auth=AuthSettings(
        issuer_url=_settings.mcp_authorization_server_url,
        resource_server_url=_settings.mcp_public_base_url,
        validate_token_resource=False,
    ),
    token_verifier=ApiTokenVerifier(build_api_client()),
)
