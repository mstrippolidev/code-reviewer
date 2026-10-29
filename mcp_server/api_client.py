import httpx

from mcp_server.config import get_mcp_settings

API_TIMEOUT_SECONDS = 10.0


def build_api_client(auth: httpx.Auth | None = None) -> httpx.AsyncClient:
    """An HTTP client for api/. Without `auth` it sends no credential, so the caller sets the header per request."""
    return httpx.AsyncClient(
        base_url=get_mcp_settings().mcp_api_base_url,
        auth=auth,
        timeout=API_TIMEOUT_SECONDS,
    )
