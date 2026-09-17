from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.user import User
from api.indexing.producer import RepoIndexProducer
from api.integrations.github import GitHubOAuthClient, GitHubOAuthConfig
from api.security.jwt_service import InvalidAccessTokenError, JwtTokenService
from api.security.token_cipher import TokenCipher

bearer_scheme = HTTPBearer(auto_error=True)


def get_database_engine(request: Request) -> DatabaseEngine:
    return request.app.state.database_engine


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    engine = get_database_engine(request)
    async with engine.new_session() as session:
        yield session


@lru_cache
def get_jwt_service() -> JwtTokenService:
    settings = get_api_settings()
    return JwtTokenService(
        secret_key=settings.api_jwt_secret_key,
        access_token_ttl_seconds=settings.api_jwt_access_token_ttl_seconds,
        state_token_ttl_seconds=settings.api_oauth_state_ttl_seconds,
    )


@lru_cache
def get_token_cipher() -> TokenCipher:
    settings = get_api_settings()
    return TokenCipher(encryption_key=settings.api_token_encryption_key)


def get_frontend_base_url() -> str:
    return get_api_settings().frontend_base_url


def get_kafka_producer(request: Request) -> RepoIndexProducer:
    return request.app.state.kafka_producer


def get_github_oauth_client(request: Request) -> GitHubOAuthClient:
    settings = get_api_settings()
    config = GitHubOAuthConfig(
        client_id=settings.github_oauth_client_id,
        client_secret=settings.github_oauth_client_secret,
        redirect_uri=settings.github_oauth_redirect_uri,
    )
    return GitHubOAuthClient(config, request.app.state.http_client)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
) -> User:
    user_id = _verify_bearer_token(credentials.credentials, jwt_service)
    return await _load_user_by_id(user_id, session)


def _verify_bearer_token(token: str, jwt_service: JwtTokenService) -> int:
    try:
        return jwt_service.verify_access_token(token)
    except InvalidAccessTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
        ) from error


async def _load_user_by_id(user_id: int, session: AsyncSession) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
    return user
