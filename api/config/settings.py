from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class ApiSettings(BaseSettings):
    """Environment configuration for the api/ app: its own Postgres tables, GitHub OAuth, and token secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str

    api_environment: str = "local"

    api_jwt_secret_key: str
    api_jwt_access_token_ttl_seconds: int = 3600
    api_oauth_state_ttl_seconds: int = 300

    api_token_encryption_key: str

    github_oauth_client_id: str
    github_oauth_client_secret: str
    github_oauth_redirect_uri: str

    frontend_base_url: str = "http://localhost:5173"

    @property
    def async_database_url(self) -> URL:
        return self._build_database_url("postgresql+asyncpg")

    @property
    def sync_database_url(self) -> URL:
        return self._build_database_url("postgresql+psycopg2")

    def _build_database_url(self, drivername: str) -> URL:
        return URL.create(
            drivername=drivername,
            username=self.pg_user,
            password=self.pg_password,
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_database,
        )


@lru_cache
def get_api_settings() -> ApiSettings:
    return ApiSettings()
