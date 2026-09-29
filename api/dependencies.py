import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.db.engine import DatabaseEngine
from api.db.models.guest_session import GuestSession
from api.db.models.registered_repo import RegisteredRepo
from api.db.models.user import User
from api.indexing.producer import RepoIndexProducer
from api.integrations.github import GitHubOAuthClient, GitHubOAuthConfig
from api.review.review_progress_broadcaster import ReviewProgressBroadcaster
from api.security.jwt_service import InvalidAccessTokenError, InvalidGuestSessionTokenError, JwtTokenService
from api.security.token_cipher import TokenCipher
from code_reviewer.agents.registry import AgentsContainer
from code_reviewer.rag.indexer import LlamaIndexRagManager

GUEST_SESSION_COOKIE = "guest_session_token"

bearer_scheme = HTTPBearer(auto_error=True)
optional_bearer_scheme = HTTPBearer(auto_error=False)


def get_database_engine(request: Request) -> DatabaseEngine:
    return request.app.state.database_engine


@asynccontextmanager
async def short_lived_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session scoped to the caller's own block rather than the whole
    request — for a route like an SSE stream that only needs the DB for
    one lookup up front and must not hold a connection for its own
    long-running remainder. A client disconnecting mid-block cancels the
    surrounding task while it may still be inside the session's own
    close/rollback — shielding just that close from the same cancellation
    lets asyncpg finish it cleanly instead of the pool having to forcibly
    terminate a half-closed connection."""
    session = get_database_engine(request).new_session()
    try:
        yield session
    finally:
        await asyncio.shield(session.close())


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with short_lived_db_session(request) as session:
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


def get_rag_manager(request: Request) -> LlamaIndexRagManager:
    return request.app.state.rag_manager


def get_agents_container(request: Request) -> AgentsContainer:
    return request.app.state.agents_container


def get_review_broadcaster(request: Request) -> ReviewProgressBroadcaster:
    return request.app.state.review_progress_broadcaster


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


async def get_guest_session(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
) -> GuestSession:
    guest_session_id = _verify_guest_cookie(request.cookies.get(GUEST_SESSION_COOKIE), jwt_service)
    guest_session = await session.get(GuestSession, guest_session_id)
    if guest_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired guest session")
    return guest_session


def _verify_guest_cookie(token: str | None, jwt_service: JwtTokenService) -> int:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No guest session")
    try:
        return jwt_service.verify_guest_session_token(token)
    except InvalidGuestSessionTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired guest session",
        ) from error


def _optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
) -> int | None:
    if credentials is None:
        return None
    try:
        return jwt_service.verify_access_token(credentials.credentials)
    except InvalidAccessTokenError:
        return None


def _optional_guest_session_id(
    request: Request, jwt_service: JwtTokenService = Depends(get_jwt_service)
) -> int | None:
    token = request.cookies.get(GUEST_SESSION_COOKIE)
    if token is None:
        return None
    try:
        return jwt_service.verify_guest_session_token(token)
    except InvalidGuestSessionTokenError:
        return None


def require_user_or_guest(
    user_id: int | None = Depends(_optional_user_id),
    guest_session_id: int | None = Depends(_optional_guest_session_id),
) -> None:
    """Admits either a GitHub-authenticated bearer token or a guest session cookie, for read-only review routes."""
    if user_id is None and guest_session_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")


async def require_registered_repo(
    repo_id: int, session: AsyncSession = Depends(get_db_session)
) -> RegisteredRepo:
    """Shared by any route (repos, reviews) that acts on an already-registered repo."""
    repo = await session.scalar(select(RegisteredRepo).where(RegisteredRepo.repo_id == repo_id))
    if repo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Repo {repo_id} is not registered")
    return repo
