from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.config.settings import get_api_settings
from api.dependencies import get_db_session, get_jwt_service, get_redis, user_id_from_session_cookie
from api.oauth.authorization_code_service import AuthorizationCodeService
from api.oauth.authorization_flow import AuthorizationFlow
from api.oauth.client_service import OAuthClientService
from api.oauth.token_grants import TokenGrantHandler
from api.oauth.token_repository import OAuthTokenRepository
from api.oauth.token_service import OAuthTokenService, TokenLifetimes
from api.security.jwt_service import JwtTokenService


def get_oauth_issuer() -> str:
    return get_api_settings().api_public_base_url.rstrip("/")


def get_oauth_client_service(session: AsyncSession = Depends(get_db_session)) -> OAuthClientService:
    return OAuthClientService(session)


def get_authorization_code_service(redis: Redis = Depends(get_redis)) -> AuthorizationCodeService:
    return AuthorizationCodeService(redis, get_api_settings().oauth_code_ttl_seconds)


def get_oauth_token_service(session: AsyncSession = Depends(get_db_session)) -> OAuthTokenService:
    settings = get_api_settings()
    lifetimes = TokenLifetimes(
        access_seconds=settings.oauth_access_token_ttl_seconds,
        refresh_idle_seconds=settings.oauth_refresh_idle_ttl_seconds,
        refresh_absolute_seconds=settings.oauth_refresh_absolute_ttl_seconds,
    )
    return OAuthTokenService(OAuthTokenRepository(session), lifetimes)


def get_authorization_flow(
    clients: OAuthClientService = Depends(get_oauth_client_service),
    codes: AuthorizationCodeService = Depends(get_authorization_code_service),
) -> AuthorizationFlow:
    return AuthorizationFlow(clients, codes)


def get_token_grant_handler(
    clients: OAuthClientService = Depends(get_oauth_client_service),
    codes: AuthorizationCodeService = Depends(get_authorization_code_service),
    tokens: OAuthTokenService = Depends(get_oauth_token_service),
) -> TokenGrantHandler:
    return TokenGrantHandler(clients, codes, tokens)


def get_session_user_id(request: Request, jwt_service: JwtTokenService = Depends(get_jwt_service)) -> int | None:
    """The browser session's user, or None. Cookie only: an OAuth bearer token must not be able to approve clients."""
    return user_id_from_session_cookie(request, jwt_service)


def require_session_user_id(user_id: int | None = Depends(get_session_user_id)) -> int:
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return user_id
