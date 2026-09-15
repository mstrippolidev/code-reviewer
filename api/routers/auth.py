from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.user import User
from api.dependencies import (
    get_current_user,
    get_db_session,
    get_frontend_base_url,
    get_github_oauth_client,
    get_jwt_service,
    get_token_cipher,
)
from api.integrations.github import (
    GitHubOAuthClient,
    GitHubOAuthLoginError,
    GitHubProfileFetchError,
    GitHubRepoAccessLevel,
    GitHubRepoFetchError,
    GitHubTokenGrant,
)
from api.schemas.auth import UserRead
from api.schemas.github import GitHubRepo, GitHubUserProfile
from api.security.jwt_service import InvalidOAuthStateError, JwtTokenService
from api.security.token_cipher import TokenCipher

router = APIRouter(prefix="/api/oauth/github", tags=["Auth"])


@dataclass(frozen=True)
class AuthenticatedGitHubIdentity:
    """A GitHub profile plus the encrypted token and scopes granted for this login."""

    profile: GitHubUserProfile
    encrypted_github_token: str
    granted_scopes: str


@router.get("/login")
async def login(
    access_level: GitHubRepoAccessLevel = Query(default=GitHubRepoAccessLevel.ALL),
    github_oauth_client: GitHubOAuthClient = Depends(get_github_oauth_client),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
) -> RedirectResponse:
    state = jwt_service.issue_oauth_state()
    authorize_url = github_oauth_client.build_authorize_url(state=state, access_level=access_level)
    return RedirectResponse(authorize_url)


@router.get("/callback")
async def callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    github_oauth_client: GitHubOAuthClient = Depends(get_github_oauth_client),
    jwt_service: JwtTokenService = Depends(get_jwt_service),
    token_cipher: TokenCipher = Depends(get_token_cipher),
    session: AsyncSession = Depends(get_db_session),
    frontend_base_url: str = Depends(get_frontend_base_url),
) -> RedirectResponse:
    _reject_denied_or_incomplete_callback(code, state, error)
    _verify_state(state, jwt_service)

    token_grant = await _fetch_github_token_grant(code, github_oauth_client)
    profile = await _fetch_github_profile(token_grant.access_token, github_oauth_client)
    identity = AuthenticatedGitHubIdentity(
        profile=profile,
        encrypted_github_token=token_cipher.encrypt(token_grant.access_token),
        granted_scopes=token_grant.granted_scopes,
    )

    user = await _create_or_update_user_from_github_login(identity, session)
    access_token = jwt_service.issue_access_token(user_id=user.id)
    redirect_url = f"{frontend_base_url}/callback?token={access_token}"
    return RedirectResponse(redirect_url)


@router.get("/me")
async def read_current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get("/repos")
async def list_repos(
    page: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    github_oauth_client: GitHubOAuthClient = Depends(get_github_oauth_client),
    token_cipher: TokenCipher = Depends(get_token_cipher),
) -> list[GitHubRepo]:
    access_token = token_cipher.decrypt(current_user.encrypted_github_token)
    try:
        return await github_oauth_client.fetch_user_repos(access_token, page)
    except GitHubRepoFetchError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch the GitHub repo list",
        ) from error


def _reject_denied_or_incomplete_callback(code: str | None, state: str | None, error: str | None) -> None:
    if error is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub login was not authorized")
    if code is None or state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code or state")


def _verify_state(state: str, jwt_service: JwtTokenService) -> None:
    try:
        jwt_service.verify_oauth_state(state)
    except InvalidOAuthStateError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state",
        ) from error


async def _fetch_github_token_grant(code: str, github_oauth_client: GitHubOAuthClient) -> GitHubTokenGrant:
    try:
        return await github_oauth_client.exchange_code_for_token(code)
    except GitHubOAuthLoginError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub rejected the OAuth code",
        ) from error


async def _fetch_github_profile(access_token: str, github_oauth_client: GitHubOAuthClient) -> GitHubUserProfile:
    try:
        return await github_oauth_client.fetch_user_profile(access_token)
    except GitHubProfileFetchError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not fetch the GitHub user profile",
        ) from error


async def _create_or_update_user_from_github_login(
    identity: AuthenticatedGitHubIdentity,
    session: AsyncSession,
) -> User:
    user = await session.scalar(select(User).where(User.github_id == identity.profile.github_id))
    if user is None:
        user = User(github_id=identity.profile.github_id, github_username=identity.profile.github_username)
    user.github_username = identity.profile.github_username
    user.email = identity.profile.email
    user.avatar_url = identity.profile.avatar_url
    user.encrypted_github_token = identity.encrypted_github_token
    user.github_granted_scopes = identity.granted_scopes
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
