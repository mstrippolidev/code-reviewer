from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    """Environment configuration for mcp_server/: where api/ lives, who issues tokens, and this server's own public URL."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_api_base_url: str = "http://localhost:8000"
    mcp_authorization_server_url: str = "http://localhost:8000"
    mcp_public_base_url: str = "http://localhost:8001"


@lru_cache
def get_mcp_settings() -> McpSettings:
    return McpSettings()
