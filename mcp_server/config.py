from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    """Environment configuration for mcp_server/: where api/ lives and the credential used to call it."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mcp_api_base_url: str = "http://localhost:8000"
    mcp_api_access_token: str = ""


@lru_cache
def get_mcp_settings() -> McpSettings:
    return McpSettings()
